// Runs only in a disposable GitHub-hosted Mac VM. No application is started.
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const root = __dirname;
const before = JSON.parse(fs.readFileSync(path.join(root, 'before.json')));
const boot = cp.execFileSync('/usr/sbin/sysctl', ['-n', 'kern.bootsessionuuid'], {encoding: 'utf8'}).trim();
if (boot === before.boot) process.exit(0);
Object.assign(process.env, JSON.parse(fs.readFileSync(path.join(root, 'runtime.json'))));
const {DefaultArtifactClient} = require('@actions/artifact');
async function main() {
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const user = cp.execFileSync('/usr/bin/stat', ['-f', '%Su', '/dev/console'], {encoding: 'utf8'}).trim();
      const result = {before, after: {boot, user}, rebootVerified: boot !== before.boot, recordedAt: new Date().toISOString()};
      const file = path.join(root, 'after.json');
      fs.writeFileSync(file, JSON.stringify(result, null, 2));
      await new DefaultArtifactClient().uploadArtifact('macos-actual-reboot-probe', [file], root, {retentionDays: 7});
      return;
    } catch (error) {
      // Do not print the runtime credentials or network request headers.
      console.log(`Evidence upload attempt ${attempt + 1} failed: ${error.name}`);
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }
  process.exitCode = 1;
}
main();
