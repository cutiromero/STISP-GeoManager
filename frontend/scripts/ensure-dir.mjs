import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const target = process.argv[2];
if (!target) {
  throw new Error("请提供要创建的目录路径");
}

mkdirSync(resolve(process.cwd(), target), { recursive: true });
