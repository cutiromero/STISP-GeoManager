import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const originalFields = new Set([
  "coverUrl",
  "previewUrl",
  "downloadUrl",
  "url",
]);

export function checkCardSource(filename, text) {
  const source = ts.createSourceFile(
    filename,
    text,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const errors = [];
  const imports = new Map(
    source.statements
      .filter(ts.isImportDeclaration)
      .filter((statement) => ts.isStringLiteral(statement.moduleSpecifier))
      .map((statement) => [
        statement.importClause?.name?.text,
        statement.moduleSpecifier.text,
      ]),
  );
  const vectorIcons = new Set(
    source.statements
      .filter(ts.isImportDeclaration)
      .filter(
        (statement) =>
          ts.isStringLiteral(statement.moduleSpecifier) &&
          statement.moduleSpecifier.text.endsWith(".svg"),
      )
      .map((statement) => statement.importClause?.name?.text),
  );
  function reject(node, reason) {
    const { line } = source.getLineAndCharacterOfPosition(
      node.getStart(source),
    );
    errors.push(
      `${filename}:${line + 1} ${reason}；请改用 CardCover 的 thumbnailUrl，禁止回退原图。`,
    );
  }
  function containsOriginal(node) {
    if (ts.isIdentifier(node)) {
      const imported = imports.get(node.text);
      if (
        imported &&
        /\.(png|jpe?g|webp)$/.test(imported) &&
        !imported.startsWith("@card-assets/")
      )
        return true;
    }
    if (
      ts.isElementAccessExpression(node) &&
      ts.isStringLiteral(node.argumentExpression) &&
      originalFields.has(node.argumentExpression.text)
    )
      return true;
    if (
      ts.isPropertyAccessExpression(node) &&
      originalFields.has(node.name.text)
    )
      return true;
    if (
      ts.isIdentifier(node) &&
      /(?:resultPreviewUrl|coverUrl|previewUrl|downloadUrl)$/.test(node.text)
    )
      return true;
    return Boolean(ts.forEachChild(node, containsOriginal));
  }
  function rawImages(node) {
    const opening = ts.isJsxElement(node)
      ? node.openingElement
      : ts.isJsxSelfClosingElement(node)
        ? node
        : undefined;
    if (
      opening &&
      /^(img|Image|picture)$/.test(opening.tagName.getText(source))
    ) {
      const src = opening.attributes.properties.find(
        (attribute) =>
          ts.isJsxAttribute(attribute) &&
          attribute.name.getText(source) === "src",
      );
      if (
        src?.initializer &&
        ts.isJsxExpression(src.initializer) &&
        src.initializer.expression &&
        ts.isIdentifier(src.initializer.expression) &&
        vectorIcons.has(src.initializer.expression.text)
      )
        return false;
      return true;
    }
    return Boolean(ts.forEachChild(node, rawImages));
  }
  function visit(node) {
    const opening = ts.isJsxElement(node)
      ? node.openingElement
      : ts.isJsxSelfClosingElement(node)
        ? node
        : undefined;
    if (opening) {
      const name = opening.tagName.getText(source);
      const attributes = opening.attributes.properties;
      if (name === "CardCover") {
        const thumbnail = attributes.find(
          (attribute) =>
            ts.isJsxAttribute(attribute) &&
            attribute.name.getText(source) === "thumbnailUrl",
        );
        if (thumbnail?.initializer && containsOriginal(thumbnail.initializer))
          reject(thumbnail, "卡片封面直接引用原图地址字段");
      }
      const className = attributes.find(
        (attribute) =>
          ts.isJsxAttribute(attribute) &&
          attribute.name.getText(source) === "className",
      );
      const card =
        name === "Card" ||
        Boolean(
          className?.initializer &&
          /\b[\w-]*card\b/.test(className.initializer.getText(source)),
        );
      if (card && rawImages(node))
        reject(node, "卡片内部直接使用 img/Image/picture");
      if (card) {
        for (const attribute of attributes) {
          if (
            ts.isJsxAttribute(attribute) &&
            ["cover", "style"].includes(attribute.name.getText(source)) &&
            attribute.initializer &&
            containsOriginal(attribute.initializer)
          )
            reject(attribute, "卡片封面或背景引用原图");
        }
      }
      if (filename.endsWith("Card.tsx") && /^(img|Image|picture)$/.test(name))
        reject(node, "卡片模块直接渲染图片");
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  if (filename.endsWith("teamProfile.ts")) {
    for (const statement of source.statements) {
      if (
        ts.isImportDeclaration(statement) &&
        ts.isStringLiteral(statement.moduleSpecifier) &&
        !statement.moduleSpecifier.text.startsWith("@card-assets/")
      )
        reject(statement, "团队肖像未使用构建期小图");
    }
  }
  return errors;
}

function scan(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const filename = join(folder, entry.name);
    if (entry.isDirectory())
      return entry.name === "generated" ? [] : scan(filename);
    if (
      (!filename.endsWith(".tsx") && !filename.endsWith("teamProfile.ts")) ||
      /\.test\./.test(filename) ||
      filename.endsWith("CardCover.tsx")
    )
      return [];
    return checkCardSource(filename, readFileSync(filename, "utf8"));
  });
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const errors = scan(root);
  if (errors.length) {
    console.error(errors.join("\n"));
    process.exitCode = 1;
  } else
    console.log("卡片图片规则通过：只用 CardCover 与预生成 thumbnailUrl。");
}
