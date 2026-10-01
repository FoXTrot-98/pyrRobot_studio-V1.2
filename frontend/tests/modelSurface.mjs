// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

const source=fs.readFileSync(new URL('../src/components/modelSurface.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2023}}).outputText;
const {surfaceNormals}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const near=(a,b)=>a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<1e-6,`${a} != ${b}`));
// Two shallow facets smooth together; a perpendicular cap stays sharp.
const part={vertices:[[0,0,0],[1,0,0],[0,1,0],[0,-1,0.2],[0,0,1]],faces:[[0,1,2],[1,0,3],[0,2,4]]};
const smooth=surfaceNormals(part,true),flat=surfaceNormals(part,false);
near(smooth[0][0],smooth[1][1]);
assert.ok(smooth[0][0][1]>0);
near(smooth[2][0],[1,0,0]);
near(flat[0][0],[0,0,1]);
near(surfaceNormals({...part,smoothing:['off','off','off']},true)[0][0],[0,0,1]);
near(surfaceNormals({...part,smoothing:['1','2','3']},true)[0][0],[0,0,1]);
near(surfaceNormals({...part,normals:[[[0,1,0],null,null]]},true)[0][0],[0,1,0]);
console.log('PASS: smooth facets, sharp cap, flat mode, smoothing groups and imported normals');
