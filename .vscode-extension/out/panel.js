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
    refreshFileList() {
        this.refreshFileListInternal(); // Refresh file list without updating config
    }
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
        // Send initial config to webview
        this.updateConfig();
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
                case 'all':
                    vscode.commands.executeCommand('scriptorium.all');
                    return;
                case 'getConfig':
                    this.updateConfig();
                    return;
                case 'openSettings':
                    vscode.commands.executeCommand('workbench.action.openSettings', '@ext:silberengel.scriptorium-publisher');
                    return;
                case 'addFile':
                    vscode.commands.executeCommand('scriptorium.addFile');
                    return;
                case 'openInputFolder':
                    vscode.commands.executeCommand('scriptorium.openInputFolder');
                    return;
                case 'refreshFiles':
                    this.refreshFileList();
                    return;
                case 'read':
                    vscode.commands.executeCommand('scriptorium.read');
                    return;
            }
        }, null, this._disposables);
        // Update config when settings change
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('scriptorium')) {
                this.updateConfig();
            }
        }, null, this._disposables);
    }
    async refreshFileListInternal() {
        const config = vscode.workspace.getConfiguration('scriptorium');
        const inputDir = config.get('inputDir', 'uploader/input_data');
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
            this._panel.webview.postMessage({
                type: 'files',
                files: [],
                inputDir: inputDir,
                error: 'No workspace folder open'
            });
            return;
        }
        try {
            const inputPath = vscode.Uri.joinPath(workspaceFolder.uri, inputDir);
            const files = [];
            try {
                const entries = await vscode.workspace.fs.readDirectory(inputPath);
                for (const [name, type] of entries) {
                    if (type === vscode.FileType.File) {
                        // Only show source files
                        if (name.match(/\.(html|adoc|md|rtf|epub)$/i)) {
                            files.push(name);
                        }
                    }
                }
                files.sort();
            }
            catch (err) {
                // Directory doesn't exist yet
            }
            this._panel.webview.postMessage({
                type: 'files',
                files: files,
                inputDir: inputDir
            });
        }
        catch (error) {
            this._panel.webview.postMessage({
                type: 'files',
                files: [],
                inputDir: inputDir,
                error: error.message
            });
        }
    }
    updateConfig() {
        const config = vscode.workspace.getConfiguration('scriptorium');
        this._panel.webview.postMessage({
            type: 'config',
            relayUrl: config.get('relayUrl', 'wss://thecitadel.nostr1.com'),
            sourceType: config.get('sourceType', 'HTML'),
            inputDir: config.get('inputDir', 'uploader/input_data'),
            outputDir: config.get('outputDir', 'uploader/publisher/out'),
            secretKey: config.get('secretKey', '')
        });
        this.refreshFileListInternal();
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
            width: 100%;
            max-width: 300px;
        }
        .button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        .button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .section {
            margin: 20px 0;
            padding: 15px;
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border-radius: 4px;
        }
        h2 {
            margin-top: 0;
            color: var(--vscode-textLink-foreground);
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
        .info {
            background-color: var(--vscode-textBlockQuote-background);
            padding: 10px;
            border-left: 3px solid var(--vscode-textLink-foreground);
            margin: 10px 0;
        }
        .config-section {
            margin-top: 20px;
            padding: 15px;
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border-radius: 4px;
        }
        .config-item {
            margin: 10px 0;
        }
        .config-label {
            font-weight: bold;
            display: block;
            margin-bottom: 5px;
        }
        .config-value {
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
        }
        .workflow {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .step-number {
            display: inline-block;
            width: 24px;
            height: 24px;
            background-color: var(--vscode-textLink-foreground);
            color: white;
            border-radius: 50%;
            text-align: center;
            line-height: 24px;
            margin-right: 10px;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <h1>📚 Scriptorium Publisher</h1>
    <p>Publish books and publications to Nostr</p>

    <div class="info">
        <strong>Workflow:</strong> Initialize Metadata → Generate Events → Publish to Relay → Quality Control
    </div>

    <div class="workflow">
        <div class="section">
            <h2><span class="step-number">1</span>Initialize Metadata</h2>
            <p>Generate @metadata.yml from your source file. This creates the metadata configuration needed for publishing.</p>
            <button class="button" onclick="initMetadata()" id="btn-init">Initialize Metadata</button>
        </div>

        <div class="section">
            <h2><span class="step-number">2</span>Generate Events</h2>
            <p>Convert source to AsciiDoc and generate Nostr events (kind 30040 and 30041) with NKBIP-01 and NKBIP-08 tags.</p>
            <button class="button" onclick="generate()" id="btn-generate">Generate Events</button>
        </div>

        <div class="section">
            <h2><span class="step-number">3</span>Publish to Relay</h2>
            <p>Publish generated events to your configured Nostr relay. Requires a secret key.</p>
            <button class="button" onclick="publish()" id="btn-publish">Publish</button>
        </div>

        <div class="section">
            <h2><span class="step-number">4</span>Quality Control</h2>
            <p>Verify that all events are present on the relay and optionally republish missing ones.</p>
            <button class="button" onclick="qc()" id="btn-qc">Run QC Check</button>
        </div>

                        <div class="section">
                            <h2>⚡ Quick Actions</h2>
                            <p>Run the complete workflow in one step.</p>
                            <button class="button" onclick="all()" id="btn-all">Generate & Publish All</button>
                        </div>

                        <div class="section">
                            <h2>📖 Read Publication</h2>
                            <p>Read and view publications from Nostr relays.</p>
                            <button class="button" onclick="read()" id="btn-read">Open Reader</button>
                        </div>
                    </div>

    <div class="section">
        <h2>📁 Input Files</h2>
        <p>Manage source files in your input directory</p>
        <div class="config-item">
            <span class="config-label">Input Directory:</span>
            <span class="config-value" id="config-input-dir">Loading...</span>
        </div>
        <div style="margin: 10px 0;">
            <button class="button" onclick="addFile()" style="max-width: 200px; margin-right: 10px;">➕ Add File</button>
            <button class="button" onclick="openInputFolder()" style="max-width: 200px;">📂 Open Folder</button>
            <button class="button" onclick="refreshFiles()" style="max-width: 200px;">🔄 Refresh</button>
        </div>
        <div id="file-list" style="margin-top: 15px; max-height: 200px; overflow-y: auto; padding: 10px; background-color: var(--vscode-editor-background); border-radius: 4px;">
            <p style="color: var(--vscode-descriptionForeground); font-size: 12px;">Loading files...</p>
        </div>
    </div>

    <div class="config-section">
        <h2>⚙️ Configuration</h2>
        <div class="config-item">
            <span class="config-label">Relay URL:</span>
            <span class="config-value" id="config-relay">Loading...</span>
        </div>
        <div class="config-item">
            <span class="config-label">Source Type:</span>
            <span class="config-value" id="config-source">Loading...</span>
        </div>
        <div class="config-item">
            <span class="config-label">Output Directory:</span>
            <span class="config-value" id="config-output">Loading...</span>
        </div>
        <div class="config-item">
            <span class="config-label">Secret Key:</span>
            <span class="config-value" id="config-key">Loading...</span>
        </div>
        <p style="margin-top: 10px; font-size: 12px; color: var(--vscode-descriptionForeground);">
            Configure these in VS Code Settings (Ctrl+,) under "Scriptorium Publisher"
        </p>
        <button class="button" onclick="openSettings()" style="margin-top: 10px; max-width: 200px;">⚙️ Open Settings</button>
    </div>

    <div id="status"></div>

    <script>
        const vscode = acquireVsCodeApi();

        // Load configuration
        vscode.postMessage({ command: 'getConfig' });

        function initMetadata() {
            setButtonLoading('btn-init', true);
            vscode.postMessage({ command: 'initMetadata' });
        }

        function generate() {
            setButtonLoading('btn-generate', true);
            vscode.postMessage({ command: 'generate' });
        }

        function publish() {
            setButtonLoading('btn-publish', true);
            vscode.postMessage({ command: 'publish' });
        }

        function qc() {
            setButtonLoading('btn-qc', true);
            vscode.postMessage({ command: 'qc' });
        }

        function all() {
            setButtonLoading('btn-all', true);
            vscode.postMessage({ command: 'all' });
        }

        function read() {
            vscode.postMessage({ command: 'read' });
        }

        function openSettings() {
            vscode.postMessage({ command: 'openSettings' });
        }

        function addFile() {
            vscode.postMessage({ command: 'addFile' });
        }

        function openInputFolder() {
            vscode.postMessage({ command: 'openInputFolder' });
        }

        function refreshFiles() {
            vscode.postMessage({ command: 'refreshFiles' });
        }

        function setButtonLoading(btnId, loading) {
            const btn = document.getElementById(btnId);
            if (btn) {
                btn.disabled = loading;
                if (loading) {
                    btn.textContent = 'Running...';
                }
            }
        }

        window.addEventListener('message', event => {
            const message = event.data;
            const statusDiv = document.getElementById('status');
            
            if (message.type === 'status') {
                statusDiv.innerHTML = '<div class="status ' + message.class + '">' + message.text + '</div>';
                // Reset button states after a delay
                setTimeout(() => {
                    ['btn-init', 'btn-generate', 'btn-publish', 'btn-qc', 'btn-all'].forEach(id => {
                        const btn = document.getElementById(id);
                        if (btn) {
                            btn.disabled = false;
                            btn.textContent = btn.textContent.replace('Running...', '').trim();
                        }
                    });
                }, 2000);
            } else if (message.type === 'config') {
                document.getElementById('config-relay').textContent = message.relayUrl || 'Not set';
                document.getElementById('config-source').textContent = message.sourceType || 'Not set';
                document.getElementById('config-input-dir').textContent = message.inputDir || 'Not set';
                document.getElementById('config-output').textContent = message.outputDir || 'Not set';
                document.getElementById('config-key').textContent = message.secretKey ? '***' + message.secretKey.slice(-4) : 'Not set (using env var)';
            } else if (message.type === 'files') {
                const fileListDiv = document.getElementById('file-list');
                if (message.error) {
                    fileListDiv.innerHTML = '<p style="color: var(--vscode-errorForeground);">' + message.error + '</p>';
                } else if (message.files && message.files.length > 0) {
                    let html = '<ul style="list-style: none; padding: 0; margin: 0;">';
                    message.files.forEach(file => {
                        html += '<li style="padding: 5px 0; border-bottom: 1px solid var(--vscode-panel-border);">📄 ' + file + '</li>';
                    });
                    html += '</ul>';
                    fileListDiv.innerHTML = html;
                } else {
                    fileListDiv.innerHTML = '<p style="color: var(--vscode-descriptionForeground); font-size: 12px;">No source files found in ' + (message.inputDir || 'input directory') + '</p>';
                }
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