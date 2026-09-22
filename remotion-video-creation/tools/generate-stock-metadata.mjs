import fs from "node:fs";
import path from "node:path";

const projectDir = path.resolve(import.meta.dirname, "..");
const workspaceDir = path.resolve(projectDir, "..");
const renderDir = path.join(projectDir, "renders", "local-adobe-stock");
const componentStatusPath = path.join(workspaceDir, "components", "component-status.csv");
const outputPath = path.join(renderDir, "adobe-stock-metadata.csv");

const CATEGORY = {
  environment: "5",
  graphics: "8",
  science: "16",
  technology: "19",
};

const csvEscape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;

const parseCsvLine = (line) => {
  const values = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (quoted) {
      if (char === '"' && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        current += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
};

const readCsv = (filePath) => {
  const lines = fs.readFileSync(filePath, "utf8").trim().split(/\r?\n/);
  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
  });
};

const splitWords = (value) => value
  .replace(/^\d{3}-/, "")
  .replace(/-adobe-stock(?:-retry\d+)?\.mp4$/i, "")
  .replace(/Composition|Animation|Icon|Comp|Master/g, " ")
  .replace(/([a-z])([A-Z])/g, "$1 $2")
  .replace(/[-_]+/g, " ")
  .replace(/\bECG\b/g, "ECG")
  .replace(/\bDna\b/g, "DNA")
  .replace(/\bIud\b/g, "IUD")
  .replace(/\bSTI\b/gi, "STI")
  .replace(/\s+/g, " ")
  .trim();

const titleCase = (value) => splitWords(value)
  .split(" ")
  .map((word) => {
    const upper = word.toUpperCase();
    if (["DNA", "ECG", "IUD", "STI"].includes(upper)) return upper;
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
  })
  .join(" ");

const unique = (items) => {
  const seen = new Set();
  const out = [];
  for (const item of items) {
    const cleaned = String(item ?? "").trim();
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(cleaned);
  }
  return out;
};

const includesAny = (text, terms) => terms.some((term) => text.includes(term));

const inferDomain = (subject) => {
  const text = `${subject} ${splitWords(subject)}`.toLowerCase();
  if (includesAny(text, [
    "eco", "green", "renewable", "energy", "wind", "turbine", "hydrogen",
    "sustainability", "recycle", "water recycle", "clean energy", "bulb",
    "battery", "power", "power cycle", "environment",
  ])) {
    return "environment";
  }
  if (includesAny(text, [
    "biometric", "digital", "network", "processor", "gesture", "secure",
    "threat", "scan", "technology", "tech",
  ])) {
    return "technology";
  }
  if (includesAny(text, [
    "health", "medical", "heart", "pill", "heartbeat", "anatomy", "bacteria",
    "bladder", "blood", "brain", "cell", "colon", "dna", "ear", "enzyme",
    "eye", "foot", "gallbladder", "intestine", "joint", "kidney", "leg",
    "liver", "lung", "nerve", "olfactory", "pancreas", "skeleton", "spine",
    "spleen", "stomach", "thyroid", "tissue", "tooth", "allergies",
    "autoimmune", "pain", "burn", "cancer", "chemical", "chills", "cough",
    "deaf", "dry", "fever", "diplococcus", "headache", "ribbon", "virus",
    "intestinal", "smell", "vision", "lymphoma", "diagnostic", "nausea",
    "oesophagus", "pneumonia", "prostate", "sti", "contraceptive", "iud",
    "family planning",
  ])) {
    return "science";
  }
  return "graphics";
};

const domainPhrases = {
  environment: {
    category: CATEGORY.environment,
    titleSuffix: "renewable energy motion graphic",
    keywords: [
      "renewable energy", "clean energy", "green technology", "sustainability",
      "eco friendly", "environment", "power", "electricity", "climate",
      "conservation", "recycling", "energy efficiency",
    ],
  },
  technology: {
    category: CATEGORY.technology,
    titleSuffix: "technology motion graphic",
    keywords: [
      "technology", "digital", "innovation", "data", "network", "interface",
      "cyber", "security", "scan", "system", "automation", "futuristic",
    ],
  },
  science: {
    category: CATEGORY.science,
    titleSuffix: "medical science motion graphic",
    keywords: [
      "medical", "healthcare", "science", "diagnostic", "biology", "clinical",
      "medicine", "anatomy", "health", "treatment", "research", "laboratory",
    ],
  },
  graphics: {
    category: CATEGORY.graphics,
    titleSuffix: "animated icon motion graphic",
    keywords: [
      "icon", "animated icon", "motion graphic", "graphic element", "symbol",
      "interface", "loop", "design", "clean", "minimal", "illustration",
    ],
  },
};

const extraKeywords = (subject) => {
  const text = subject.toLowerCase();
  const extras = [];
  const pairs = [
    ["heart", ["heart", "cardiology", "heartbeat", "pulse"]],
    ["blood", ["blood", "blood cells", "vascular", "circulation"]],
    ["cancer", ["cancer", "oncology", "tumor", "screening"]],
    ["virus", ["virus", "viral", "capsid", "microbiology"]],
    ["bacteria", ["bacteria", "microbiology", "pathogen", "infection"]],
    ["dna", ["DNA", "genetics", "genome", "molecular biology"]],
    ["lung", ["lungs", "respiratory", "breathing", "pulmonary"]],
    ["pneumonia", ["pneumonia", "respiratory infection", "lung disease"]],
    ["kidney", ["kidney", "renal", "urology", "organ"]],
    ["liver", ["liver", "hepatology", "organ", "diagnosis"]],
    ["pancreas", ["pancreas", "endocrine", "organ", "diagnosis"]],
    ["thyroid", ["thyroid", "endocrine", "gland", "hormone"]],
    ["tooth", ["tooth", "dental", "dentistry", "oral health"]],
    ["ear", ["ear", "hearing", "otology", "sensory"]],
    ["eye", ["eye", "vision", "ophthalmology", "sight"]],
    ["deaf", ["deaf", "hearing loss", "accessibility", "ear"]],
    ["smell", ["smell", "olfactory", "sensory", "nose"]],
    ["contraceptive", ["contraception", "birth control", "reproductive health", "family planning"]],
    ["iud", ["IUD", "contraception", "birth control", "reproductive health"]],
    ["sti", ["STI", "sexual health", "prevention", "infection"]],
    ["eco", ["eco", "sustainable", "green", "environmental"]],
    ["wind", ["wind turbine", "wind power", "renewable power", "clean electricity"]],
    ["battery", ["battery", "energy storage", "power storage", "electric"]],
    ["hydrogen", ["hydrogen", "hydrogen energy", "fuel", "clean fuel"]],
    ["water", ["water", "water recycling", "conservation", "sustainability"]],
    ["biometric", ["biometric", "identity", "scan", "authentication"]],
    ["secure", ["secure", "security", "protection", "guarantee"]],
    ["network", ["network", "nodes", "connection", "data visualization"]],
  ];
  for (const [needle, values] of pairs) {
    if (text.includes(needle)) extras.push(...values);
  }
  return extras;
};

const makeTitle = (subject, domain) => {
  const cleanSubject = titleCase(subject);
  const suffix = domainPhrases[domain].titleSuffix;
  const title = `Animated ${cleanSubject} icon for ${suffix}`;
  return title.length <= 200 ? title : title.slice(0, 197).trimEnd() + "...";
};

const makeKeywords = (subject, domain, width, height) => {
  const subjectWords = splitWords(subject).split(" ");
  const subjectPhrase = titleCase(subject).toLowerCase();
  const base = [
    subjectPhrase,
    ...subjectWords,
    ...extraKeywords(subject),
    ...domainPhrases[domain].keywords,
    "animation",
    "animated",
    "motion graphics",
    "looping animation",
    "video",
    "footage",
    "icon animation",
    "line art",
    "flat design",
    "abstract",
    "modern",
    width === height ? "square video" : "4k video",
    `${width}x${height}`,
  ];
  return unique(base).slice(0, 49).join(", ");
};

const components = readCsv(componentStatusPath);
const componentByRow = new Map(components.map((row) => [row.SourceFile.slice(0, 3), row]));
const mp4s = fs.readdirSync(renderDir)
  .filter((name) => name.toLowerCase().endsWith(".mp4"))
  .sort();

const rows = mp4s.map((file) => {
  const row = file.slice(0, 3);
  const component = componentByRow.get(row);
  const subject = component?.CompositionId ?? file;
  const domain = inferDomain(subject);
  const note = component?.Notes ?? "";
  const sizeMatch = note.match(/(\d+)x(\d+)/);
  const width = sizeMatch ? Number(sizeMatch[1]) : file.includes("3840") ? 3840 : 1080;
  const height = sizeMatch ? Number(sizeMatch[2]) : width === 3840 ? 2160 : 1080;
  return {
    Filename: file,
    Title: makeTitle(subject, domain),
    Keywords: makeKeywords(subject, domain, width, height),
    Category: domainPhrases[domain].category,
    Releases: "",
  };
});

const lines = [
  ["Filename", "Title", "Keywords", "Category", "Releases"],
  ...rows.map((row) => [row.Filename, row.Title, row.Keywords, row.Category, row.Releases]),
];

fs.writeFileSync(outputPath, lines.map((line) => line.map(csvEscape).join(",")).join("\n") + "\n");

const invalid = rows.flatMap((row, index) => {
  const issues = [];
  if (row.Title.length > 200) issues.push(`row ${index + 1}: title too long`);
  if (row.Keywords.split(",").length > 49) issues.push(`row ${index + 1}: too many keywords`);
  if (!row.Filename.endsWith(".mp4")) issues.push(`row ${index + 1}: filename is not mp4`);
  return issues;
});

if (invalid.length > 0) {
  console.error(invalid.join("\n"));
  process.exit(1);
}

console.log(JSON.stringify({
  outputPath,
  rows: rows.length,
  categories: Object.fromEntries(
    Object.entries(
      rows.reduce((acc, row) => {
        acc[row.Category] = (acc[row.Category] ?? 0) + 1;
        return acc;
      }, {}),
    ).sort(([a], [b]) => Number(a) - Number(b)),
  ),
}, null, 2));
