import { strict as assert } from "node:assert";
import { describe, it } from "node:test";
import { evaluate } from "../src/evaluate.js";
import { loadPacks } from "../src/packs.js";
import { detectProtocol, extractCommand } from "../src/hook.js";
import { loadConfig } from "../src/config.js";
import fs from "node:fs";
import path from "node:path";

const packs=loadPacks();
describe("TypeScript HAL parity fixtures",()=>{
  for(const [command,blocked] of [["git push --force",true],["git push --force-with-lease",false],["git commit -m 'rm -rf /'",false],["rm -rf /",true],["rm -rf node_modules",false],["aws ec2 terminate-instances --instance-ids i-1",true],["docker system prune -a",true]] as const)
    it(command,()=>assert.equal(evaluate(command,packs).action==="block",blocked));
  it("extracts both hook protocols",()=>{assert.equal(extractCommand({toolInput:{command:"git push --force"}}),"git push --force");assert.equal(detectProtocol({toolInput:{command:"x"}}),"copilot");assert.equal(detectProtocol({tool_input:{command:"x"}}),"claude");});
  it("evaluates heredocs piped to interpreters",()=>{
    assert.equal(evaluate("bash <<EOF\nrm -rf /\nEOF",packs).action,"block");
    assert.equal(evaluate("cat <<'END' | sh\ngit push --force\nEND",packs).action,"block");
    assert.equal(evaluate("cat <<EOF\nrm -rf /\nEOF",packs).action,"allow");
  });
  it("loads project config and concatenates list settings",()=>{
    const home=fs.mkdtempSync(path.join(process.cwd(),".hal-home-test-"));
    const dir=fs.mkdtempSync(path.join(process.cwd(),".hal-config-test-"));
    const packDir=path.join(dir,"custom-packs"); fs.mkdirSync(packDir);
    fs.writeFileSync(path.join(packDir,"custom.yaml"),"name: custom\nkeywords: [danger]\nrules:\n  - id: test\n    has_all: [danger, erase]\n    severity: block\n");
    fs.mkdirSync(path.join(home,".config","hal"),{recursive:true});
    fs.writeFileSync(path.join(home,".config","hal","config.yaml"),"packs: [global.pack]\npack_dirs: [global/packs]\nallow: [echo global]\n");
    fs.writeFileSync(path.join(dir,".hal.yaml"),`packs: [project.pack]\npack_dirs: [${packDir}]\nallow: [echo safe]\n`);
    const oldHome=process.env.HOME; process.env.HOME=home;
    const config=loadConfig(dir);
    assert.deepEqual(config.packs,["global.pack","project.pack"]);
    assert.deepEqual(config.pack_dirs,["global/packs",packDir]);
    assert.deepEqual(config.allow,["echo global","echo safe"]);
    assert.equal(loadPacks(config.pack_dirs)[0].rules[0].rule_id,"custom:test");
    process.env.HOME=oldHome;
    fs.rmSync(home,{recursive:true,force:true}); fs.rmSync(dir,{recursive:true,force:true});
  });
});
