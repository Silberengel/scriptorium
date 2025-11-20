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
exports.ScriptoriumPanel = void 0;
const vscode = __importStar(require("vscode"));
const path = __importStar(require("path"));
class ScriptoriumPanel {
    static createOrShow(extensionPath) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;
        if (ScriptoriumPanel.currentPanel) {
            ScriptoriumPanel.currentPanel._panel.reveal(column);
            return;
        }
        const panel = vscode.window.createWebviewPanel(ScriptoriumPanel.viewType, 'Scriptorium Publisher', column || vscode.ViewColumn.One, {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.file(path.join(extensionPath, 'media'))
            ]
        });
        ScriptoriumPanel.currentPanel = new ScriptoriumPanel(panel, extensionPath);
    }
    constructor(panel, extensionPath) {
        this._disposables = [];
        this._panel = panel;
        this._extensionPath = extensionPath;
        this._update();
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(message => {
            switch (message.command) {
                case 'initMetadata':
                    vscode.commands.executeCommand('scriptorium.initMetadata');
                    return;
                case 'generate':
                    vscode.commands.executeCommand('scriptorium.generate');
                    return;
                case 'publish':
                    vscode.commands.executeCommand('scriptorium.publish');
                    return;
                case 'qc':
                    vscode.commands.executeCommand('scriptorium.qc');
                    return;
            }
        }, null, this._disposables);
    }
    dispose() {
        ScriptoriumPanel.currentPanel = undefined;
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
    _update() {
        const webview = this._panel.webview;
        this._panel.webview.html = this._getHtmlForWebview(webview);
    }
    _getHtmlForWebview(webview) {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scriptorium Publisher</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 20px;
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
        }
        .button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 10px 20px;
            margin: 5px;
            cursor: pointer;
            border-radius: 2px;
            font-size: 14px;
        }
        .button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        .section {
            margin: 20px 0;
            padding: 15px;
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border-radius: 4px;
        }
        h2 {
            margin-top: 0;
        }
        .status {
            margin-top: 10px;
            padding: 10px;
            border-radius: 4px;
        }
        .success {
            background-color: var(--vscode-testing-iconPassed);
            color: white;
        }
        .error {
            background-color: var(--vscode-testing-iconFailed);
            color: white;
        }
    </style>
</head>
<body>
    <h1>📚 Scriptorium Publisher</h1>
    <p>Publish books and publications to Nostr</p>

    <div class="section">
        <h2>1. Initialize Metadata</h2>
        <p>Generate @metadata.yml from your source file</p>
        <button class="button" onclick="initMetadata()">Initialize Metadata</button>
    </div>

    <div class="section">
        <h2>2. Generate Events</h2>
        <p>Convert source to AsciiDoc and generate Nostr events</p>
        <button class="button" onclick="generate()">Generate Events</button>
    </div>

    <div class="section">
        <h2>3. Publish to Relay</h2>
        <p>Publish generated events to your Nostr relay</p>
        <button class="button" onclick="publish()">Publish</button>
    </div>

    <div class="section">
        <h2>4. Quality Control</h2>
        <p>Verify events are present on the relay</p>
        <button class="button" onclick="qc()">Run QC Check</button>
    </div>

    <div class="section">
        <h2>Quick Actions</h2>
        <button class="button" onclick="all()">Generate & Publish All</button>
    </div>

    <div id="status"></div>

    <script>
        const vscode = acquireVsCodeApi();

        function initMetadata() {
            vscode.postMessage({ command: 'initMetadata' });
        }

        function generate() {
            vscode.postMessage({ command: 'generate' });
        }

        function publish() {
            vscode.postMessage({ command: 'publish' });
        }

        function qc() {
            vscode.postMessage({ command: 'qc' });
        }

        function all() {
            vscode.postMessage({ command: 'all' });
        }

        window.addEventListener('message', event => {
            const message = event.data;
            const statusDiv = document.getElementById('status');
            if (message.type === 'status') {
                statusDiv.innerHTML = '<div class="status ' + message.class + '">' + message.text + '</div>';
            }
        });
    </script>
</body>
</html>`;
    }
}
exports.ScriptoriumPanel = ScriptoriumPanel;
ScriptoriumPanel.viewType = 'scriptoriumPanel';
//# sourceMappingURL=panel.js.map