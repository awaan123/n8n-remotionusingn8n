import fs from "node:fs";
import path from "node:path";

const projectDir = path.resolve(import.meta.dirname, "..");
const workspaceDir = path.resolve(projectDir, "..");
const payloadDir = path.join(workspaceDir, "components");
const statusPath = path.join(payloadDir, "component-status.csv");
const videosDir = path.join(projectDir, "src", "videos");

const csvEscape = (value) => `"${String(value).replaceAll('"', '""')}"`;

const getPayloadText = (raw) => {
  const parsed = JSON.parse(raw);
  const root = Array.isArray(parsed) ? parsed[0] : parsed;

  if (typeof root?.text === "string") {
    return root.text;
  }

  const content = root?.choices?.[0]?.message?.content ??
    root?.data?.choices?.[0]?.message?.content;
  if (typeof content !== "string") {
    throw new Error("No generated message content found");
  }

  return content;
};

const normalizeSourcePath = (sourcePath) => {
  return sourcePath
    .replaceAll("\\", "/")
    .replace(/^\/+/, "")
    .replace(/[)`'"*:,]+$/g, "")
    .replace(/^\.\//, "");
};

const findBlockPath = (text, fenceIndex, code) => {
  const commentMatch = code
    .split(/\r?\n/, 6)
    .join("\n")
    .match(/(?:\/\/|\/\*)\s*\/?(src\/[A-Za-z0-9_.\-/]+\.(?:tsx?|jsx?))/i);
  if (commentMatch) {
    return normalizeSourcePath(commentMatch[1]);
  }

  const prefix = text.slice(Math.max(0, fenceIndex - 500), fenceIndex);
  const candidates = [
    ...prefix.matchAll(/\/?src\/[A-Za-z0-9_.\-/]+\.(?:tsx?|jsx?)/gi),
  ];

  if (candidates.length > 0) {
    return normalizeSourcePath(candidates.at(-1)[0]);
  }

  const shortCandidates = [
    ...prefix.matchAll(/(?:File:\s*)?[`'"*]*(?:\/)?([A-Za-z0-9_.\-/]+\.(?:tsx?|jsx?))/gi),
  ];
  if (shortCandidates.length > 0) {
    const candidate = normalizeSourcePath(shortCandidates.at(-1)[1]);
    return candidate.startsWith("src/") ? candidate : `src/${candidate}`;
  }

  return null;
};

const extractBlocks = (text) => {
  const blocks = [];
  const fencePattern = /```(?:tsx|typescript|ts|jsx|javascript|js)\s*\r?\n([\s\S]*?)```/gi;

  for (const match of text.matchAll(fencePattern)) {
    blocks.push({
      sourcePath: findBlockPath(text, match.index, match[1]),
      code: match[1].trimEnd() + "\n",
    });
  }

  return blocks;
};

const componentDeclarations = (text) => {
  const declarations = [];
  const compositionPattern = /<Composition\b([\s\S]*?)(?:\/>|>)/g;

  for (const match of text.matchAll(compositionPattern)) {
    const body = match[1];
    const component = body.match(/\bcomponent\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}/)?.[1];
    const id = body.match(/\bid\s*=\s*["']([^"']+)["']/)?.[1];
    if (component) {
      declarations.push({ component, id });
    }
  }

  return declarations;
};

const exportedComponents = (blocks) => {
  const results = [];
  const exportPattern = /export\s+(?:default\s+)?(?:const|function|class)\s+([A-Za-z_$][\w$]*)/g;

  for (const block of blocks) {
    for (const match of block.code.matchAll(exportPattern)) {
      results.push({ name: match[1], sourcePath: block.sourcePath });
    }
  }

  return results;
};

const chooseCandidate = (text, blocks) => {
  const exports = exportedComponents(blocks);
  const declaration = componentDeclarations(text).find((item) =>
    exports.some((entry) => entry.name === item.component),
  );

  if (declaration) {
    const exported = exports.find((entry) => entry.name === declaration.component);
    return { ...declaration, sourcePath: exported.sourcePath };
  }

  const ignored = new Set([
    "Root",
    "RemotionRoot",
    "Background",
    "compositionConfig",
    "registerRoot",
  ]);
  const scored = exports
    .filter((entry) => entry.sourcePath && !ignored.has(entry.name))
    .map((entry) => {
      let score = 0;
      if (/Animation|Composition|Icon|Badge|Cycle|Process|Assembly/i.test(entry.name)) score += 10;
      if (/\/(?:index|Root)\.tsx$/i.test(entry.sourcePath)) score += 6;
      if (/components?\//i.test(entry.sourcePath)) score += 2;
      return { ...entry, score };
    })
    .sort((a, b) => b.score - a.score);

  const candidate = scored[0];
  return candidate
    ? { component: candidate.name, id: candidate.name, sourcePath: candidate.sourcePath }
    : null;
};

const numberFrom = (text, patterns, fallback) => {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return Number(match[1]);
  }
  return fallback;
};

const buildRecords = () => {
  const files = fs
    .readdirSync(payloadDir)
    .filter((file) => /^\d{3}_.+\.txt$/i.test(file))
    .sort();

  const seenIds = new Map();
  return files.map((file, index) => {
    const text = getPayloadText(fs.readFileSync(path.join(payloadDir, file), "utf8"));
    const blocks = extractBlocks(text);
    const candidate = chooseCandidate(text, blocks);
    if (!candidate) {
      throw new Error(`${file}: could not identify an exported Remotion component`);
    }

    const baseId = (candidate.id || candidate.component).replace(/[^A-Za-z0-9_-]/g, "-");
    const occurrence = (seenIds.get(baseId) ?? 0) + 1;
    seenIds.set(baseId, occurrence);
    const compositionId = occurrence === 1 ? baseId : `${baseId}-${String(index + 1).padStart(3, "0")}`;
    const sourceBlock = blocks.find(
      (block) => block.sourcePath === candidate.sourcePath &&
        new RegExp(`export\\s+(?:default\\s+)?(?:const|function|class)\\s+${candidate.component}\\b`).test(block.code),
    );
    if (!sourceBlock?.sourcePath) {
      throw new Error(`${file}: no source path found for ${candidate.component}`);
    }

    const row = file.slice(0, 3);
    const driveId = file.slice(4, -4);
    return {
      row,
      file,
      driveId,
      text,
      blocks,
      componentName: candidate.component,
      sourcePath: candidate.sourcePath,
      compositionId,
      width: numberFrom(text, [/<Composition\b[^>]*?\bwidth\s*=\s*\{?\s*(\d+)/, /\bCANVAS_WIDTH\s*=\s*(\d+)/, /\bCANVAS_SIZE\s*=\s*(\d+)/, /\bCANVAS\s*=\s*(\d+)/], 1080),
      height: numberFrom(text, [/<Composition\b[^>]*?\bheight\s*=\s*\{?\s*(\d+)/, /\bCANVAS_HEIGHT\s*=\s*(\d+)/, /\bCANVAS_SIZE\s*=\s*(\d+)/, /\bCANVAS\s*=\s*(\d+)/], 1080),
      fps: numberFrom(text, [/<Composition\b[\s\S]*?\bfps\s*=\s*\{?\s*(\d+)/i, /\bFPS\s*=\s*(\d+)/, /\bfps\s*=\s*\{?\s*(\d+)/i], 30),
      durationInFrames: numberFrom(text, [/<Composition\b[\s\S]*?\bdurationInFrames\s*=\s*\{?\s*(\d+)/i, /\bDURATION(?:_IN_FRAMES)?\s*=\s*(\d+)/, /\bdurationInFrames\s*=\s*\{?\s*(\d+)/i], 240),
    };
  });
};

const writeStatusCsv = (records, statuses = new Map()) => {
  const lines = [
    ["SourceFile", "DriveFileId", "ComponentName", "CompositionId", "Status", "Notes"],
    ...records.map((record) => [
      record.file,
      record.driveId,
      record.componentName,
      record.compositionId,
      statuses.get(record.file) ?? "unregistered",
      `${record.blocks.length} code blocks analyzed`,
    ]),
  ];
  fs.writeFileSync(statusPath, lines.map((line) => line.map(csvEscape).join(",")).join("\n") + "\n");
};

const importPathFor = (sourcePath) => sourcePath.replace(/\.(?:tsx?|jsx?)$/i, "");

const even = (value) => Math.max(2, Math.round(value / 2) * 2);

const targetFor = ({ width, height }) => {
  if (width === height) {
    const target = width > 1080 ? 2160 : 1080;
    return { targetWidth: target, targetHeight: target, scale: target / width };
  }

  if (width > height) {
    return { targetWidth: 3840, targetHeight: 2160, scale: 3840 / width };
  }

  return { targetWidth: 2160, targetHeight: 3840, scale: 3840 / height };
};

const repairKnownGenerationTypos = (code) => {
  return code
    .replace(/\binterpolateColor\b/g, "interpolateColors")
    .replace(/\btension\s*:/g, "stiffness:")
    .replace(
      /import type \{\s*SpringConfig\s*\} from ['"]remotion['"];?/g,
      `import type {SpringConfig as RemotionSpringConfig} from 'remotion';\ntype SpringConfig = Partial<RemotionSpringConfig>;`,
    )
    .replaceAll(
      "Easing.inOut(Easing.cos)",
      "Easing.inOut((value) => (1 - Math.cos(Math.PI * value)) / 2)",
    )
    .replace(
      /TRACHEA_START,\r?\n\s*getGlowOpacity,/g,
      "TRACHEA_START,\n  TRACHEA_END,\n  getGlowOpacity,",
    )
    .replace(
      /import \{\s*BATTERY_COLOR,\s*CENTER\s*\} from ["']\.\/CycleBatteryIcon["'];/g,
      `const BATTERY_COLOR = "#121315";\nconst CENTER = 540;`,
    )
    .replace(
      /import \{\s*COLORS,\s*GLOBE_CENTER,\s*GLOBE_R\s*\} from ["']\.\.\/EcoTechGlobe["'];/g,
      `const COLORS = {bg: '#F2F4F7', charcoal: '#1E272E', green: '#10AC84', emerald: '#2ED573'};\nconst GLOBE_CENTER = {x: 480, y: 420};\nconst GLOBE_R = 180;`,
    )
    .replace(
      /import \{\s*STROKE,\s*STROKE_WIDTH\s*\} from ["']\.\.\/ProtectedImmunityIcon["'];/g,
      `const STROKE = '#12131A';\nconst STROKE_WIDTH = 24;`,
    )
    .replace(
      "[start, start + 15, 135], [0, 1, 0.5]",
      "[start, start + 15, start + 30], [0, 1, 0.5]",
    )
    .replace(
      /import React from ['"]react \{ Composition \} from ['"]remotion['"];?/g,
      `import React from 'react';\nimport { Composition } from 'remotion';`,
    )
    .replace(
      /^import \{ RemotionRoot \} from ['"]\.\.\/\.\.\/Root['"];?[^\r\n]*\r?\n/gm,
      "",
    )
    .replace(
      /import \{DISK_COUNT, GEOMETRY, PHASES, rangeProgress, easeInOutQuad\} from ['"]\.\/constants['"];?\r?\nimport \{easeInOutQuad as ease\} from ['"]\.\/easing['"];?/g,
      `import {DISK_COUNT, GEOMETRY, PHASES} from './constants';\nimport {easeInOutQuad as ease, rangeProgress} from './easing';`,
    )
    .replaceAll(
      "Easing.out(Easing.quart)",
      "Easing.out((value) => value ** 4)",
    )
    .replaceAll("Easing.inOut(Easing.expo)", "Easing.inOut(Easing.exp)")
    .replaceAll(
      "progress={playProgress}",
      "progress={playOpacity}",
    )
    .replace(
      /<svg viewBox=\{`0 0 \$\{CANVAS_SIZE\} \$\{CANVAS_SIZE\}`\} width="100%" height="100%">/g,
      `<svg\n        viewBox={\`0 0 \${CANVAS_SIZE} \${CANVAS_SIZE}\`}\n        width="100%"\n        height="100%"\n        style={{position: 'absolute', inset: 0}}\n      >`,
    );
};

const wrapperNameFor = (record) => {
  const safeName = record.componentName.replace(/[^A-Za-z0-9_$]/g, "");
  return `Payload${record.row}${safeName}`;
};

const writeGeneratedSources = (records) => {
  const generatedDir = path.join(videosDir, "generated");
  if (path.dirname(generatedDir) !== videosDir || path.basename(generatedDir) !== "generated") {
    throw new Error(`Refusing to clean unexpected generated path: ${generatedDir}`);
  }
  fs.mkdirSync(videosDir, { recursive: true });
  fs.rmSync(generatedDir, { recursive: true, force: true });
  for (const file of fs.readdirSync(videosDir)) {
    if (/^Payload\d{3}.+\.tsx$/.test(file)) {
      fs.unlinkSync(path.join(videosDir, file));
    }
  }
  fs.mkdirSync(generatedDir, { recursive: true });

  for (const record of records) {
    const packageDir = path.join(generatedDir, record.row);
    fs.mkdirSync(packageDir, { recursive: true });
    const pathsSeen = new Set();

    for (const block of record.blocks) {
      if (
        /^src\/(?:Root\.tsx|index\.ts)$/i.test(block.sourcePath ?? "") &&
        block.sourcePath !== record.sourcePath
      ) {
        continue;
      }
      if (!block.sourcePath || pathsSeen.has(block.sourcePath)) continue;
      pathsSeen.add(block.sourcePath);
      const outputPath = path.join(packageDir, ...block.sourcePath.split("/"));
      fs.mkdirSync(path.dirname(outputPath), { recursive: true });
      fs.writeFileSync(
        outputPath,
        `/* eslint-disable */\n// @ts-nocheck -- imported generated payload; runtime-checked by Remotion bundling.\n${repairKnownGenerationTypos(block.code)}`,
      );
    }

    const wrapperName = wrapperNameFor(record);
    const targetImport = `./generated/${record.row}/${importPathFor(record.sourcePath)}`;
    const wrapperPath = path.join(videosDir, `${wrapperName}.tsx`);
    fs.writeFileSync(
      wrapperPath,
      `import type React from "react";\n` +
        `import { ${record.componentName} } from "${targetImport}";\n\n` +
        `const Target = ${record.componentName} as unknown as React.ComponentType<Record<string, unknown>>;\n\n` +
        `export const ${wrapperName}: React.FC = () => (\n` +
        `  <Target\n` +
        `    color="#111111"\n` +
        `    iconColor="#111111"\n` +
        `    baseColor="#111111"\n` +
        `    lineColor="#111111"\n` +
        `    strokeColor="#111111"\n` +
        `    primaryColor="#111111"\n` +
        `    secondaryColor="#555555"\n` +
        `    backgroundColor="#f2f2f2"\n` +
        `    background="#f2f2f2"\n` +
        `    bgColor="#f2f2f2"\n` +
        `    bg="#f2f2f2"\n` +
        `    strokeWidth={12}\n` +
        `    size={1080}\n` +
        `    scale={1}\n` +
        `    scaleFactor={1}\n` +
        `    rotationSpeed={1}\n` +
        `    RotationSpeed={1}\n` +
        `    OrbitSpeed={1}\n` +
        `    Scale={1}\n` +
        `  />\n` +
        `);\n`,
    );
  }
};

const buildRootSource = (records) => {
  const imports = records
    .map((record) => {
      const name = wrapperNameFor(record);
      return `import { ${name} } from "./videos/${name}";`;
    })
    .join("\n");
  const compositions = records
    .map((record) => {
      const name = wrapperNameFor(record);
      return `      <Composition\n` +
        `        id="${record.compositionId}"\n` +
        `        component={${name}}\n` +
        `        width={${record.width}}\n` +
        `        height={${record.height}}\n` +
        `        durationInFrames={${record.durationInFrames}}\n` +
        `        fps={${record.fps}}\n` +
        `        defaultProps={{}}\n` +
        `      />`;
    })
    .join("\n");

  return `import "./index.css";\n` +
    `import { Composition } from "remotion";\n` +
    `${imports}\n\n` +
    `export const RemotionRoot: React.FC = () => {\n` +
    `  return (\n` +
    `    <>\n` +
    `${compositions}\n` +
    `    </>\n` +
    `  );\n` +
    `};\n`;
};

const updateModalJobs = (records) => {
  const modalPath = path.join(projectDir, "modal_render.py");
  const source = fs.readFileSync(modalPath, "utf8");
  const jobs = records
    .map((record) => {
      const target = targetFor(record);
      return (
      `        {\n` +
      `            "id": "${record.row}-${record.compositionId}",\n` +
      `            "composition_id": "${record.compositionId}",\n` +
      `            "width": ${record.width},\n` +
      `            "height": ${record.height},\n` +
      `            "target_width": ${even(target.targetWidth)},\n` +
      `            "target_height": ${even(target.targetHeight)},\n` +
      `            "scale": ${target.scale},\n` +
      `            "props": {},\n` +
      `        },`
      );
    })
    .join("\n");
  const jobsPattern = /^    jobs(?::[^\r\n=]+)?\s*=\s*(?:\[\]|\[[\s\S]*?^    \])/m;
  if (!jobsPattern.test(source)) {
    throw new Error("Could not locate the jobs list in modal_render.py");
  }
  const updated = source.replace(
    jobsPattern,
    `    jobs = [\n${jobs}\n    ]`,
  );
  fs.writeFileSync(modalPath, updated);
};

const main = () => {
  if (process.argv.includes("--clear-registrations")) {
    fs.writeFileSync(
      path.join(projectDir, "src", "Root.tsx"),
      `import "./index.css";\n\n` +
        `// Rendered component sources were removed after their MP4s were verified.\n` +
        `export const RemotionRoot = () => null;\n`,
    );
    updateModalJobs([]);
    console.log("Cleared Root.tsx compositions and modal render jobs.");
    return;
  }

  const records = buildRecords();
  const statuses = process.argv.includes("--mark-registered")
    ? new Map(records.map((record) => [record.file, "registered"]))
    : new Map();
  writeStatusCsv(records, statuses);
  const missingPaths = records.flatMap((record) =>
    record.blocks
      .filter((block) => !block.sourcePath)
      .map(() => record.file),
  );
  console.log(`Analyzed ${records.length} payloads.`);
  console.log(`Wrote ${statusPath}`);
  console.log(`Code blocks without a recoverable path: ${missingPaths.length}`);
  if (missingPaths.length > 0) {
    console.log([...new Set(missingPaths)].join("\n"));
  }

  if (process.argv.includes("--generate")) {
    writeGeneratedSources(records);
    fs.writeFileSync(path.join(projectDir, "src", "Root.tsx"), buildRootSource(records));
    updateModalJobs(records);
    console.log(`Generated and registered ${records.length} Remotion components.`);
  }
};

main();
