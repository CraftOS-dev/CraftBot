#!/usr/bin/env node
const path = require('path');
const { spawn } = require('child_process');
const index = require('./index.js');

// If required as module, export everything from index
if (require.main !== module) {
    module.exports = index;
    // Also support default export as recall function for v1 compatibility
    // if index.recall exists.
    if (index.recall) {
        module.exports.recall = index.recall;
        // Some consumers might expect module.exports itself to be the function?
        // Let's stick to named exports for now as v2.0.0 index.js uses named exports.
    }
} else {
    // CLI mode
    const args = process.argv.slice(2);
    const commands = ['recall', 'search', 'digest', 'log-event', 'sync-groups', 'add-group', 'list-groups'];
    
    // Check if the first argument is a command supported by index.js
    let commandToRun = [];
    if (args.length === 0 || !commands.includes(args[0])) {
        // Default to 'recall' command for backward compatibility
        // (v1 usage: node recall.js --user ...)
        commandToRun.push('recall');
    }
    
    const finalArgs = [path.join(__dirname, 'index.js'), ...commandToRun, ...args];
    
    const child = spawn(process.execPath, finalArgs, { 
        stdio: 'inherit',
        env: process.env // Pass environment variables
    });
    
    child.on('close', code => process.exit(code));
    child.on('error', err => {
        console.error('Failed to spawn child process:', err);
        process.exit(1);
    });
}
