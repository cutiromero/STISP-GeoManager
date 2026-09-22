import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const packageJsonPath = require.resolve("mapbox-gl/package.json");
const packageRoot = path.dirname(packageJsonPath);
const runtimeBundlePath = require.resolve("mapbox-gl");
const productionBundlePath = path.join(packageRoot, "dist", "mapbox-gl.js");
const developmentBundlePath = path.join(
  packageRoot,
  "dist",
  "mapbox-gl-dev.js",
);
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const productionBundle = fs.readFileSync(productionBundlePath, "utf8");
const developmentBundle = fs.readFileSync(developmentBundlePath, "utf8");

assert.equal(packageJson.version, "3.25.0");
assert.equal(
  path.normalize(runtimeBundlePath),
  path.normalize(productionBundlePath),
);

function countOccurrences(source, value) {
  return source.split(value).length - 1;
}

const drawRasterStart = developmentBundle.indexOf("function drawRaster(");
const drawPoleStart = developmentBundle.indexOf(
  "function drawPole(",
  drawRasterStart,
);
const drawPoleEnd = developmentBundle.indexOf(
  "function cutoffParamsForElevation(",
  drawPoleStart,
);
assert.ok(drawRasterStart >= 0 && drawPoleStart > drawRasterStart);
assert.ok(drawPoleEnd > drawPoleStart);

const drawRaster = developmentBundle.slice(drawRasterStart, drawPoleStart);
const drawPole = developmentBundle.slice(drawPoleStart, drawPoleEnd);
assert.equal(
  countOccurrences(
    drawRaster,
    "\n      texture.bind(textureFilter, gl.CLAMP_TO_EDGE, ignoreMipMap)",
  ),
  1,
  "current raster texture bind must bypass mipmaps",
);
assert.equal(
  countOccurrences(
    drawRaster,
    "\n        texture.bind(textureFilter, gl.CLAMP_TO_EDGE, ignoreMipMap)",
  ),
  1,
  "no-parent raster texture bind must bypass mipmaps",
);
assert.equal(
  countOccurrences(
    drawRaster,
    "parentTile.texture.bind(textureFilter, gl.CLAMP_TO_EDGE, ignoreMipMap)",
  ),
  1,
  "loaded parent raster texture bind must bypass mipmaps",
);
assert.equal(
  countOccurrences(
    drawPole,
    "\n  texture.bind(textureFilter, gl.CLAMP_TO_EDGE, ignoreMipMap)",
  ),
  2,
  "both globe-pole texture units must bypass mipmaps",
);
assert.equal(
  countOccurrences(
    drawRaster,
    'if (!ignoreMipMap && "useMipmap" in texture && context.extTextureFilterAnisotropic',
  ),
  1,
  "nearest raster draw must not overwrite the per-bind anisotropy reset",
);
assert.equal(
  countOccurrences(
    drawPole,
    'if (!ignoreMipMap && "useMipmap" in texture && context.extTextureFilterAnisotropic',
  ),
  1,
  "nearest globe-pole draw must not overwrite the per-bind anisotropy reset",
);

assert.equal(
  countOccurrences(productionBundle, "R.bind(b,f.CLAMP_TO_EDGE,b===f.NEAREST)"),
  2,
  "runtime bundle must patch current and no-parent binds",
);
assert.equal(
  countOccurrences(
    productionBundle,
    "k.texture.bind(b,f.CLAMP_TO_EDGE,b===f.NEAREST)",
  ),
  1,
  "runtime bundle must patch the loaded-parent bind",
);
assert.equal(
  countOccurrences(productionBundle, "_.bind(g,m.CLAMP_TO_EDGE,g===m.NEAREST)"),
  2,
  "runtime bundle must patch both globe-pole binds",
);
assert.equal(
  countOccurrences(
    productionBundle,
    "r&&n.extTextureFilterAnisotropic&&i.texParameterf(i.TEXTURE_2D,n.extTextureFilterAnisotropic.TEXTURE_MAX_ANISOTROPY_EXT,1)",
  ),
  1,
  "runtime Texture.bind must reset ignored-mipmap anisotropy to one",
);
assert.equal(
  countOccurrences(
    productionBundle,
    'b!==f.NEAREST&&"useMipmap"in R&&_.extTextureFilterAnisotropic',
  ),
  1,
  "runtime raster draw must not overwrite nearest anisotropy",
);
assert.equal(
  countOccurrences(
    productionBundle,
    'g!==m.NEAREST&&"useMipmap"in _&&p.extTextureFilterAnisotropic',
  ),
  1,
  "runtime globe-pole draw must not overwrite nearest anisotropy",
);

function extractMethod(source, marker) {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `Missing method marker: ${marker}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`Unterminated method marker: ${marker}`);
}

function compileBindMethod(source, marker, invariant) {
  const method = extractMethod(source, marker);
  return new Function("assert", `return function ${method};`)(invariant);
}

function verifyMinFilterCache(bind) {
  const calls = [];
  const gl = {
    TEXTURE_2D: 3553,
    TEXTURE_MAG_FILTER: 10240,
    TEXTURE_MIN_FILTER: 10241,
    TEXTURE_WRAP_S: 10242,
    TEXTURE_WRAP_T: 10243,
    NEAREST: 9728,
    LINEAR: 9729,
    NEAREST_MIPMAP_NEAREST: 9984,
    LINEAR_MIPMAP_LINEAR: 9987,
    CLAMP_TO_EDGE: 33071,
    bindTexture: (...args) => calls.push(["bindTexture", ...args]),
    texParameteri: (...args) => calls.push(["texParameteri", ...args]),
    texParameterf: (...args) => calls.push(["texParameterf", ...args]),
  };
  const anisotropyExtension = { TEXTURE_MAX_ANISOTROPY_EXT: 34046 };
  const texture = {
    context: { gl, extTextureFilterAnisotropic: anisotropyExtension },
    texture: {},
    useMipmap: true,
  };
  const minFilters = () =>
    calls
      .filter(
        ([name, , parameter]) =>
          name === "texParameteri" && parameter === gl.TEXTURE_MIN_FILTER,
      )
      .map(([, , , value]) => value);
  const anisotropyValues = () =>
    calls
      .filter(
        ([name, , parameter]) =>
          name === "texParameterf" &&
          parameter === anisotropyExtension.TEXTURE_MAX_ANISOTROPY_EXT,
      )
      .map(([, , , value]) => value);

  bind.call(texture, gl.LINEAR, gl.CLAMP_TO_EDGE, false);
  gl.texParameterf(
    gl.TEXTURE_2D,
    anisotropyExtension.TEXTURE_MAX_ANISOTROPY_EXT,
    8,
  );
  bind.call(texture, gl.NEAREST, gl.CLAMP_TO_EDGE, true);
  bind.call(texture, gl.NEAREST, gl.CLAMP_TO_EDGE, true);
  bind.call(texture, gl.NEAREST, gl.CLAMP_TO_EDGE, false);

  assert.deepEqual(minFilters(), [
    gl.LINEAR_MIPMAP_LINEAR,
    gl.NEAREST,
    gl.NEAREST_MIPMAP_NEAREST,
  ]);
  assert.deepEqual(anisotropyValues(), [8, 1, 1]);
  assert.equal(texture.magFilter, gl.NEAREST);
  assert.equal(texture.minFilter, gl.NEAREST_MIPMAP_NEAREST);
}

const invariant = (condition, message) => {
  if (!condition) throw new Error(message);
};
verifyMinFilterCache(
  compileBindMethod(
    developmentBundle,
    "bind(filter, wrap, ignoreMipMap = false)",
    invariant,
  ),
);
verifyMinFilterCache(
  compileBindMethod(productionBundle, "bind(e,t,r=!1)", invariant),
);

console.log(
  `Verified mapbox-gl ${packageJson.version} nearest-raster mipmap/anisotropy patch in ${runtimeBundlePath}`,
);
