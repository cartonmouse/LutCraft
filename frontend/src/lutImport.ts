import type { Lut } from "./types";

export type LutImportStatus = "queued" | "uploading" | "imported" | "existing" | "failed";
export type LutImportItem = { file: File; metadataFile?: File; status: LutImportStatus; error?: string; name?: string };
export type LutImportOptions = { color_space: "srgb" | "unknown"; publisher: string; source_page: string };
export type LutUploadResult = Lut & { import_status: "imported" | "existing" };

export const MAX_LUT_FILES = 50;
export const MAX_LUT_BYTES = 10 * 1024 * 1024;

export function selectLutFiles(files: File[]): { items: LutImportItem[]; ignored: number } {
  // Pair sidecars by directory. Never match nested assets by basename alone.
  const cubes = files.filter((file) => /\.cube$/i.test(file.name));
  if (!cubes.length) throw new Error("没有找到 .cube 文件，请选择 lut-library/luts 文件夹或 LUT 文件。");
  if (cubes.length > MAX_LUT_FILES) throw new Error(`每批最多 ${MAX_LUT_FILES} 个 LUT，请分批选择。`);
  if (cubes.reduce((total, file) => total + file.size, 0) > 100 * 1024 * 1024)
    throw new Error("每批总大小不能超过 100 MB，请分批选择。");
  return {
    items: cubes.map((file) => {
      const path = file.webkitRelativePath || file.name;
      const dir = path.slice(0, path.lastIndexOf("/") + 1);
      const metadataFile = files.find((f) => (f.webkitRelativePath || f.name) === dir + "metadata.json");
      return { file, metadataFile, status: "queued" };
    }),
    ignored: files.length - cubes.length,
  };
}

export async function importLutFiles(
  items: LutImportItem[],
  upload: (file: File, metadata?: Record<string, unknown>) => Promise<LutUploadResult>,
  update: (index: number, item: LutImportItem, lut?: LutUploadResult) => void,
) {
  const result = [...items];
  for (let index = 0; index < items.length; index++) {
    const item = items[index];
    if (item.status === "imported" || item.status === "existing") continue;
    update(index, { ...item, status: "uploading" });
    try {
      if (item.file.size > MAX_LUT_BYTES) throw new Error("单个 LUT 不能超过 10 MB。");
      let metadata: Record<string, unknown> | undefined;
      if (item.metadataFile) {
        if (item.metadataFile.size > 24000) throw new Error("元信息文件不能超过 24 KB。");
        const parsed = JSON.parse(await item.metadataFile.text());
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("元信息必须是 JSON 对象。");
        if (parsed.filename && parsed.filename !== item.file.name) throw new Error("元信息声明的文件名不匹配，请检查对应目录。");
        metadata = parsed;
      }
      const lut = await upload(item.file, metadata);
      result[index] = { ...item, status: lut.import_status, name: lut.name, error: undefined };
      update(index, result[index], lut);
    } catch (error) {
      result[index] = { ...item, status: "failed", error: error instanceof Error ? error.message : "导入失败，请重试。" };
      update(index, result[index]);
    }
  }
  return result;
}
