import fs from "node:fs";
import path from "node:path";
import {
  getCompositions,
  renderStill,
} from "@remotion/renderer";

const projectDir = path.resolve(import.meta.dirname, "..");
const serveUrl = path.join(projectDir, "build");
const outputDir = path.join(projectDir, "renders", "_validation_frames_current");

fs.mkdirSync(outputDir, {recursive: true});

const compositions = await getCompositions(serveUrl, {
  inputProps: {},
  logLevel: "warn",
});

for (const [index, composition] of compositions.entries()) {
  const frame = Math.min(
    composition.durationInFrames - 1,
    Math.floor(composition.durationInFrames * 0.55),
  );
  const safeId = composition.id.replace(/[^A-Za-z0-9_-]/g, "_");
  const output = path.join(
    outputDir,
    `${String(index + 1).padStart(3, "0")}-${safeId}.png`,
  );

  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      await renderStill({
        composition,
        serveUrl,
        output,
        frame,
        inputProps: {},
        imageFormat: "png",
        scale: 0.15,
        overwrite: true,
        logLevel: "warn",
      });
      break;
    } catch (error) {
      if (attempt === 2) throw error;
      console.warn(`Retrying ${composition.id} after compositor failure.`);
    }
  }

  console.log(
    `Validated ${index + 1}/${compositions.length}: ${composition.id} at frame ${frame}`,
  );
}
