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
                }
            },
            null,
            this._disposables
        );
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

