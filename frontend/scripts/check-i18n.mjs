import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import ts from "typescript";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const resourcePath = path.join(frontendRoot, "src", "i18n", "resources.ts");
const source = fs.readFileSync(resourcePath, "utf8");
const sourceFile = ts.createSourceFile(
  resourcePath,
  source,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TS,
);

function unwrapExpression(node) {
  let current = node;
  while (
    ts.isAsExpression(current) ||
    ts.isParenthesizedExpression(current) ||
    ts.isSatisfiesExpression(current)
  ) {
    current = current.expression;
  }
  return current;
}

function propertyName(node) {
  if (ts.isIdentifier(node) || ts.isStringLiteral(node)) return node.text;
  return undefined;
}

function localeObject(variableName) {
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (
        !ts.isIdentifier(declaration.name) ||
        declaration.name.text !== variableName
      ) {
        continue;
      }
      const initializer = declaration.initializer
        ? unwrapExpression(declaration.initializer)
        : undefined;
      if (!initializer || !ts.isObjectLiteralExpression(initializer)) {
        throw new Error(`${variableName} must be an object literal`);
      }
      return initializer;
    }
  }
  throw new Error(`Missing locale resource: ${variableName}`);
}

function collectLeafKeys(object, prefix = "") {
  const keys = new Set();
  for (const property of object.properties) {
    if (!ts.isPropertyAssignment(property)) continue;
    const name = propertyName(property.name);
    if (!name) continue;
    const key = prefix ? `${prefix}.${name}` : name;
    const value = unwrapExpression(property.initializer);
    if (ts.isObjectLiteralExpression(value)) {
      for (const child of collectLeafKeys(value, key)) keys.add(child);
    } else {
      keys.add(key);
    }
  }
  return keys;
}

function translationKeys(variableName) {
  const root = localeObject(variableName);
  const translation = root.properties.find(
    (property) =>
      ts.isPropertyAssignment(property) &&
      propertyName(property.name) === "translation",
  );
  if (!translation || !ts.isPropertyAssignment(translation)) {
    throw new Error(`${variableName}.translation is missing`);
  }
  const value = unwrapExpression(translation.initializer);
  if (!ts.isObjectLiteralExpression(value)) {
    throw new Error(`${variableName}.translation must be an object literal`);
  }
  return collectLeafKeys(value);
}

function filesUnder(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (["generated", "node_modules"].includes(entry.name)) return [];
      return filesUnder(fullPath);
    }
    return /\.(ts|tsx)$/.test(entry.name) ? [fullPath] : [];
  });
}

const zhKeys = translationKeys("zhCN");
const enKeys = translationKeys("enUS");
const missingInEnglish = [...zhKeys].filter((key) => !enKeys.has(key));
const missingInChinese = [...enKeys].filter((key) => !zhKeys.has(key));
const usedKeys = new Set();
const keyPattern = /\bt\(\s*["']([a-zA-Z0-9_.-]+)["']/g;
for (const file of filesUnder(path.join(frontendRoot, "src"))) {
  const text = fs.readFileSync(file, "utf8");
  for (const match of text.matchAll(keyPattern)) usedKeys.add(match[1]);
}
const unknownUsedKeys = [...usedKeys].filter(
  (key) => !zhKeys.has(key) || !enKeys.has(key),
);

if (
  missingInEnglish.length ||
  missingInChinese.length ||
  unknownUsedKeys.length
) {
  if (missingInEnglish.length) {
    console.error("Missing English keys:", missingInEnglish.join(", "));
  }
  if (missingInChinese.length) {
    console.error("Missing Chinese keys:", missingInChinese.join(", "));
  }
  if (unknownUsedKeys.length) {
    console.error("Unknown used keys:", unknownUsedKeys.join(", "));
  }
  process.exitCode = 1;
} else {
  console.log(
    `i18n resources are aligned: ${zhKeys.size} keys; ${usedKeys.size} statically referenced keys verified.`,
  );
}
