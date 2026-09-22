import path from "node:path";
import ts from "typescript";

const configPath = ts.findConfigFile(process.cwd(), ts.sys.fileExists, "tsconfig.json");
if (!configPath) {
  throw new Error("tsconfig.json was not found");
}

const config = ts.readConfigFile(configPath, ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(
  config.config,
  ts.sys,
  path.dirname(configPath),
);
const host = ts.createCompilerHost(parsed.options);
const originalGetSourceFile = host.getSourceFile.bind(host);

host.getSourceFile = (fileName, languageVersion, onError, shouldCreateNewSourceFile) => {
  const original = originalGetSourceFile(
    fileName,
    languageVersion,
    onError,
    shouldCreateNewSourceFile,
  );
  if (!original || !fileName.replaceAll("\\", "/").includes("/src/videos/")) {
    return original;
  }

  const unsuppressed = original.text
    .replace(/^\/\* eslint-disable \*\/\r?\n/, "")
    .replace(/^\/\/ @ts-nocheck[^\r\n]*\r?\n/, "");
  return ts.createSourceFile(
    fileName,
    unsuppressed,
    languageVersion,
    true,
    original.scriptKind,
  );
};

const program = ts.createProgram({
  rootNames: parsed.fileNames,
  options: parsed.options,
  host,
});

const isExpectedGeneratedNoise = (diagnostic) => {
  const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
  return diagnostic.code === 6133 ||
    (diagnostic.code === 2322 && message.includes("LooseComponentType"));
};

const diagnostics = ts
  .getPreEmitDiagnostics(program)
  .filter((diagnostic) =>
    diagnostic.category === ts.DiagnosticCategory.Error &&
    diagnostic.file &&
    diagnostic.file.fileName.replaceAll("\\", "/").includes("/src/videos/") &&
    !isExpectedGeneratedNoise(diagnostic),
  );

if (diagnostics.length > 0) {
  for (const diagnostic of diagnostics) {
    const position = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start ?? 0);
    const file = path.relative(process.cwd(), diagnostic.file.fileName);
    const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
    console.error(`${file}:${position.line + 1} TS${diagnostic.code} ${message}`);
  }
  console.error(`Generated runtime diagnostics failed with ${diagnostics.length} error(s).`);
  process.exit(1);
}

console.log("Generated runtime diagnostics passed with suppressions removed in memory.");
