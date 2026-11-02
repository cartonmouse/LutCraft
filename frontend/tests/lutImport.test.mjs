import test from "node:test";
import assert from "node:assert/strict";
import { selectLutFiles, importLutFiles, MAX_LUT_BYTES } from "../src/lutImport.ts";

const file = (name) => new File(["test cube"], name);
const uploaded = (id, status = "imported") => ({ id, name: id, sha256: id, grid_size: 33, byte_size: 9, import_status: status });

test("folder selection keeps nested LUT files and ignores metadata", () => {
  const a = file("a.cube"), b = file("B.CUBE");
  Object.defineProperty(a, "webkitRelativePath", { value: "luts/film/a/a.cube" });
  const result = selectLutFiles([a, file("metadata.json"), b, file("preview.jpg")]);
  assert.equal(result.ignored, 2);
  assert.deepEqual(result.items.map((item) => item.file), [a, b]);
  assert.equal(result.items[0].file.webkitRelativePath, "luts/film/a/a.cube");
});

test("empty, oversized batches and too many files are rejected before upload", () => {
  assert.throws(() => selectLutFiles([file("notes.txt")]), /没有找到/);
  assert.throws(() => selectLutFiles(Array.from({ length: 51 }, (_, i) => file(`${i}.cube`))), /50/);
  const large = file("large.cube");
  Object.defineProperty(large, "size", { value: 101 * 1024 * 1024 });
  assert.throws(() => selectLutFiles([large]), /100 MB/);
});

test("a failed upload does not stop the batch, and retry only sends failed files", async () => {
  const { items } = selectLutFiles([file("first.cube"), file("broken.cube"), file("last.cube")]);
  const calls = [], changes = [];
  const results = await importLutFiles(items, async (f) => {
    calls.push(f.name);
    if (f.name === "broken.cube") throw new Error("网络中断");
    return uploaded(f.name, f.name === "last.cube" ? "existing" : "imported");
  }, (index, item) => changes.push([index, item.status]));
  assert.deepEqual(calls, ["first.cube", "broken.cube", "last.cube"]);
  assert.deepEqual(results.map((item) => item.status), ["imported", "failed", "existing"]);
  assert.equal(results[1].error, "网络中断");
  assert.deepEqual(changes, [[0, "uploading"], [0, "imported"], [1, "uploading"], [1, "failed"], [2, "uploading"], [2, "existing"]]);
  const retried = [];
  const final = await importLutFiles(results, async (f) => {
    retried.push(f.name);
    return uploaded(f.name, "existing");
  }, () => {});
  assert.deepEqual(retried, ["broken.cube"]);
  assert.deepEqual(final.map((item) => item.status), ["imported", "existing", "existing"]);
});

test("an oversized file fails locally while the next LUT is imported", async () => {
  const large = file("large.cube");
  Object.defineProperty(large, "size", { value: MAX_LUT_BYTES + 1 });
  const calls = [];
  const results = await importLutFiles(selectLutFiles([large, file("small.cube")]).items, async (f) => {
    calls.push(f.name);
    return uploaded(f.name);
  }, () => {});
  assert.deepEqual(calls, ["small.cube"]);
  assert.equal(results[0].status, "failed");
  assert.match(results[0].error, /10 MB/);
  assert.equal(results[1].status, "imported");
});

test("metadata pairs by full folder path and survives retry", async () => {
  const a = file("same.cube"), b = file("same.cube");
  const meta = new File([JSON.stringify({ filename: "same.cube", tags: ["冷色"] })], "metadata.json");
  Object.defineProperty(a, "webkitRelativePath", { value: "luts/a/same.cube" });
  Object.defineProperty(b, "webkitRelativePath", { value: "luts/b/same.cube" });
  Object.defineProperty(meta, "webkitRelativePath", { value: "luts/b/metadata.json" });
  const { items } = selectLutFiles([a, b, meta]);
  assert.equal(items[0].metadataFile, undefined);
  assert.equal(items[1].metadataFile, meta);
  const calls = [];
  const results = await importLutFiles(items, async (f, m) => {
    calls.push(m);
    if (m) throw new Error("网络中断");
    return uploaded(f.name);
  }, () => {});
  assert.deepEqual(calls, [undefined, { filename: "same.cube", tags: ["冷色"] }]);
  assert.equal(results[1].metadataFile, meta);
});

test("mismatched or malformed sidecar fails before sending LUT", async () => {
  for (const data of ["not-json", JSON.stringify({ filename: "other.cube" }), "[]"]) {
    const { items } = selectLutFiles([file("same.cube"), new File([data], "metadata.json")]);
    const results = await importLutFiles(items, async () => { assert.fail("must not upload"); }, () => {});
    assert.equal(results[0].status, "failed");
  }
});
