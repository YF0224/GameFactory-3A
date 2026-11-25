// Reproduce dependency output without loading delivered configuration or game code.
import {pathToFileURL} from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
const [original, root] = process.argv.slice(2);
fs.copyFileSync(path.join(original, 'package.json'), path.join(root, 'package.json'));
fs.cpSync(path.join(original, 'node_modules'), path.join(root, 'node_modules'), {recursive:true, dereference:true});
process.chdir(root);
const {resolveConfig, optimizeDeps} = await import(pathToFileURL(path.join(original, 'node_modules/vite/dist/node/index.js')));
const config = await resolveConfig({root, configFile:false, envFile:false,
  cacheDir:'.cache/vite', resolve:{preserveSymlinks:true},
  optimizeDeps:{include:['three'], noDiscovery:true}, logLevel:'error'}, 'serve');
await optimizeDeps(config, true);
