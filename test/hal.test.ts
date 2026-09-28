import { strict as assert } from "node:assert";
import { it } from "node:test";
import { evaluate } from "../src/evaluate.js";
import { loadPacks } from "../src/packs.js";
import { detectProtocol, extractCommand } from "../src/hook.js";

const packs=loadPacks();
it("blocks destructive commands and allows safe exceptions",()=>{
  assert.equal(evaluate("git push --force",packs).action,"block");
  assert.equal(evaluate("git push --force-with-lease",packs).action,"allow");
  assert.equal(evaluate("rm -rf node_modules",packs).action,"allow");
});
it("evaluates heredocs and preserves hook protocol extraction",()=>{
  assert.equal(evaluate("bash <<EOF\nrm -rf /\nEOF",packs).action,"block");
  assert.equal(evaluate("cat <<'END' | sh\ngit push --force\nEND",packs).action,"block");
  assert.equal(extractCommand({toolInput:{command:"git push --force"}}),"git push --force");
  assert.equal(detectProtocol({toolInput:{command:"x"}}),"copilot");
});
