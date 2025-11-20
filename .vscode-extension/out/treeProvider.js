"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ScriptoriumProvider = void 0;
const vscode = __importStar(require("vscode"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
class ScriptoriumProvider {
    constructor(extensionPath) {
        this.extensionPath = extensionPath;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    }
    refresh() {
        this._onDidChangeTreeData.fire();
    }
    getTreeItem(element) {
        return element;
    }
    getChildren(element) {
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
            return Promise.resolve([]);
        }
        if (!element) {
            // Root level - show summary
            const config = vscode.workspace.getConfiguration('scriptorium');
            const outDir = config.get('outputDir', 'uploader/publisher/out');
            const eventsPath = path.join(workspaceFolder.uri.fsPath, outDir, 'events', 'events.ndjson');
            const cachePath = path.join(workspaceFolder.uri.fsPath, outDir, 'cache', 'event_index.json');
            const items = [];
            if (fs.existsSync(eventsPath)) {
                try {
                    const content = fs.readFileSync(eventsPath, 'utf-8');
                    const eventCount = content.split('\n').filter(line => line.trim()).length;
                    items.push(new EventItem(`Events: ${eventCount}`, vscode.TreeItemCollapsibleState.None, eventsPath));
                }
                catch (e) {
                    // Ignore
                }
            }
            if (fs.existsSync(cachePath)) {
                try {
                    const content = JSON.parse(fs.readFileSync(cachePath, 'utf-8'));
                    items.push(new EventItem(`Index: ${content.count || 0} d-tags`, vscode.TreeItemCollapsibleState.None, cachePath));
                }
                catch (e) {
                    // Ignore
                }
            }
            if (items.length === 0) {
                items.push(new EventItem('No events generated yet', vscode.TreeItemCollapsibleState.None));
            }
            return Promise.resolve(items);
        }
        return Promise.resolve([]);
    }
}
exports.ScriptoriumProvider = ScriptoriumProvider;
class EventItem extends vscode.TreeItem {
    constructor(label, collapsibleState, filePath) {
        super(label, collapsibleState);
        this.label = label;
        this.collapsibleState = collapsibleState;
        this.filePath = filePath;
        if (filePath) {
            this.command = {
                command: 'vscode.open',
                title: 'Open File',
                arguments: [vscode.Uri.file(filePath)]
            };
            this.tooltip = filePath;
        }
    }
}
//# sourceMappingURL=treeProvider.js.map