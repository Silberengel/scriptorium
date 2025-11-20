import * as vscode from 'vscode';
import * as path from 'path';

export class ScriptoriumPanel {
    public static currentPanel: ScriptoriumPanel | undefined;
    public static readonly viewType = 'scriptoriumPanel';
    private readonly _panel: vscode.WebviewPanel;
    private readonly _extensionPath: string;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionPath: string) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        if (ScriptoriumPanel.currentPanel) {
            ScriptoriumPanel.currentPanel._panel.reveal(column);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            ScriptoriumPanel.viewType,
            'Scriptorium Publisher',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                localResourceRoots: [
                    vscode.Uri.file(path.join(extensionPath, 'media'))
                ]
            }
        );

        ScriptoriumPanel.currentPanel = new ScriptoriumPanel(panel, extensionPath);
    }

    private constructor(panel: vscode.WebviewPanel, extensionPath: string) {
        this._panel = panel;
        this._extensionPath = extensionPath;

        this._update();

        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        // Send initial config to webview
        this.updateConfig();

        this._panel.webview.onDidReceiveMessage(
            message => {
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
                }
            },
            null,
            this._disposables
        );

        // Update config when settings change
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('scriptorium')) {
                this.updateConfig();
            }
        }, null, this._disposables);
    }

    private updateConfig() {
        const config = vscode.workspace.getConfiguration('scriptorium');
        this._panel.webview.postMessage({
            type: 'config',
            relayUrl: config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com'),
            sourceType: config.get<string>('sourceType', 'HTML'),
            outputDir: config.get<string>('outputDir', 'uploader/publisher/out'),
            secretKey: config.get<string>('secretKey', '')
        });
    }

    public dispose() {
        ScriptoriumPanel.currentPanel = undefined;

        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }

    private _update() {
        const webview = this._panel.webview;
        this._panel.webview.html = this._getHtmlForWebview(webview);
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
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

        function openSettings() {
            vscode.postMessage({ command: 'openSettings' });
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
                document.getElementById('config-output').textContent = message.outputDir || 'Not set';
                document.getElementById('config-key').textContent = message.secretKey ? '***' + message.secretKey.slice(-4) : 'Not set (using env var)';
            }
        });
    </script>
</body>
</html>`;
    }
}

