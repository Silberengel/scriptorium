import * as vscode from 'vscode';
import * as path from 'path';
import { spawn } from 'child_process';
import { findPythonCommand } from './extension';

export class ReaderPanel {
    public static currentPanel: ReaderPanel | undefined;
    public static readonly viewType = 'scriptoriumReader';
    private readonly _panel: vscode.WebviewPanel;
    private readonly _extensionPath: string;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionPath: string): ReaderPanel {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        if (ReaderPanel.currentPanel) {
            ReaderPanel.currentPanel._panel.reveal(column);
            return ReaderPanel.currentPanel;
        }

        const panel = vscode.window.createWebviewPanel(
            ReaderPanel.viewType,
            'Scriptorium Reader',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                localResourceRoots: [
                    vscode.Uri.file(path.join(extensionPath, 'media'))
                ]
            }
        );

        ReaderPanel.currentPanel = new ReaderPanel(panel, extensionPath);
        return ReaderPanel.currentPanel;
    }

    public triggerRead(eventRef: string, relayUrl: string) {
        this._panel.webview.postMessage({
            command: 'read',
            eventRef: eventRef,
            relayUrl: relayUrl
        });
    }

    private constructor(panel: vscode.WebviewPanel, extensionPath: string) {
        this._panel = panel;
        this._extensionPath = extensionPath;

        this._update();

        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        this._panel.webview.onDidReceiveMessage(
            async message => {
                switch (message.command) {
                    case 'read':
                        await this.readPublication(message.eventRef, message.relayUrl);
                        return;
                    case 'getConfig':
                        this.updateConfig();
                        return;
                }
            },
            null,
            this._disposables
        );

        // Send initial config
        this.updateConfig();
    }

    private updateConfig() {
        const config = vscode.workspace.getConfiguration('scriptorium');
        this._panel.webview.postMessage({
            type: 'config',
            relayUrl: config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com')
        });
    }

    private async readPublication(eventRef: string, relayUrl: string) {
        this._panel.webview.postMessage({
            type: 'status',
            text: 'Fetching publication...',
            class: 'info'
        });

        // Clear previous publication
        this._panel.webview.postMessage({
            type: 'clear'
        });

        try {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                throw new Error('No workspace folder open');
            }

            const pythonCmd = await findPythonCommand();
            
            const env = { ...process.env };
            
            // Use spawn to stream output line-by-line
            const pythonProcess = spawn(pythonCmd, [
                '-m', 'uploader.publisher.scripts.read_publication',
                eventRef,
                relayUrl
            ], {
                cwd: workspaceFolder.uri.fsPath,
                env,
                stdio: ['ignore', 'pipe', 'pipe']
            });

            let stdoutBuffer = '';
            let stderrBuffer = '';
            const events: any[] = [];
            let finalPublication: any = null;

            // Handle stdout (events and final publication)
            pythonProcess.stdout.on('data', (data: Buffer) => {
                stdoutBuffer += data.toString();
                const lines = stdoutBuffer.split('\n');
                stdoutBuffer = lines.pop() || ''; // Keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.trim()) continue;
                    
                    try {
                        const json = JSON.parse(line);
                        
                        if (json.type === 'event') {
                            events.push(json.event);
                            // Send event immediately to webview
                            this._panel.webview.postMessage({
                                type: 'event',
                                event: json.event,
                                count: events.length
                            });
                        } else if (json.type === 'publication') {
                            finalPublication = json.publication;
                            // Send final publication
                            this._panel.webview.postMessage({
                                type: 'publication',
                                publication: json.publication
                            });
                        }
                    } catch (e) {
                        // Not JSON, ignore
                    }
                }
            });

            // Handle stderr (progress and status)
            pythonProcess.stderr.on('data', (data: Buffer) => {
                stderrBuffer += data.toString();
                const lines = stderrBuffer.split('\n');
                stderrBuffer = lines.pop() || ''; // Keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.trim()) continue;
                    
                    try {
                        const json = JSON.parse(line);
                        
                        if (json.type === 'status') {
                            this._panel.webview.postMessage({
                                type: 'status',
                                text: json.message,
                                class: 'info'
                            });
                        } else if (json.type === 'progress') {
                            this._panel.webview.postMessage({
                                type: 'progress',
                                message: json.message,
                                count: events.length
                            });
                        } else if (json.type === 'warnings') {
                            const warningText = `Warnings (${json.count}): ${json.errors.slice(0, 3).join('; ')}${json.count > 3 ? '...' : ''}`;
                            this._panel.webview.postMessage({
                                type: 'status',
                                text: warningText,
                                class: 'info'
                            });
                        }
                    } catch (e) {
                        // Not JSON, might be plain text error
                        if (line.includes('ERROR') || line.includes('Error')) {
                            this._panel.webview.postMessage({
                                type: 'status',
                                text: line,
                                class: 'error'
                            });
                        }
                    }
                }
            });

            // Handle process completion
            pythonProcess.on('close', (code) => {
                if (code === 0) {
                    if (finalPublication) {
                        this._panel.webview.postMessage({
                            type: 'status',
                            text: `Loaded publication: ${finalPublication.metadata?.title || 'Untitled'} (${finalPublication.total_events || events.length} events)`,
                            class: 'success'
                        });
                    } else if (events.length > 0) {
                        this._panel.webview.postMessage({
                            type: 'status',
                            text: `Fetched ${events.length} events`,
                            class: 'success'
                        });
                    }
                } else {
                    this._panel.webview.postMessage({
                        type: 'status',
                        text: `Process exited with code ${code}`,
                        class: 'error'
                    });
                }
            });

            pythonProcess.on('error', (error: Error) => {
                let errorMsg = error.message || String(error);
                
                // Provide helpful message for missing dependencies
                if (errorMsg.includes('ModuleNotFoundError') || errorMsg.includes('No module named')) {
                    errorMsg = `Missing Python dependencies. Please install with:\n\npip install -r uploader/publisher/requirements.txt\n\nOr if using a virtual environment:\n.venv/bin/pip install -r uploader/publisher/requirements.txt`;
                }
                
                this._panel.webview.postMessage({
                    type: 'status',
                    text: `Error: ${errorMsg}`,
                    class: 'error'
                });
            });

        } catch (error: any) {
            let errorMsg = error.message || String(error);
            
            this._panel.webview.postMessage({
                type: 'status',
                text: `Error: ${errorMsg}`,
                class: 'error'
            });
        }
    }

    public dispose() {
        ReaderPanel.currentPanel = undefined;

        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }

    private _update() {
        this._panel.webview.html = this._getHtmlForWebview();
    }

    private _getHtmlForWebview(): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scriptorium Reader</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 20px;
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
        }
        .input-section {
            margin-bottom: 20px;
            padding: 15px;
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border-radius: 4px;
        }
        .input-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input {
            width: 100%;
            padding: 8px;
            background-color: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 2px;
            font-family: var(--vscode-font-family);
        }
        button {
            padding: 8px 16px;
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 2px;
            cursor: pointer;
            font-family: var(--vscode-font-family);
        }
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .status {
            margin: 10px 0;
            padding: 10px;
            border-radius: 4px;
        }
        .status.info {
            background-color: var(--vscode-textBlockQuote-background);
            border-left: 3px solid var(--vscode-textLink-foreground);
        }
        .status.success {
            background-color: var(--vscode-testing-iconPassed);
            color: white;
        }
        .status.error {
            background-color: var(--vscode-testing-iconFailed);
            color: white;
        }
        .publication {
            margin-top: 20px;
        }
        .metadata {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
        }
        .metadata h2 {
            margin-top: 0;
            color: var(--vscode-textLink-foreground);
        }
        .metadata-item {
            margin: 8px 0;
        }
        .metadata-label {
            font-weight: bold;
            display: inline-block;
            min-width: 120px;
        }
        .content-section {
            margin-top: 20px;
        }
        .content-item {
            margin: 15px 0;
            padding: 15px;
            background-color: var(--vscode-editor-background);
            border-left: 3px solid var(--vscode-textLink-foreground);
            border-radius: 2px;
        }
        .content-item h3 {
            margin-top: 0;
            color: var(--vscode-textLink-foreground);
        }
        .content-body {
            white-space: pre-wrap;
            font-family: var(--vscode-editor-font-family);
            line-height: 1.6;
        }
        .d-tag {
            font-size: 0.9em;
            color: var(--vscode-descriptionForeground);
            font-family: monospace;
        }
        .progress {
            margin: 10px 0;
            padding: 10px;
            background-color: var(--vscode-textBlockQuote-background);
            border-left: 3px solid var(--vscode-textLink-foreground);
            border-radius: 4px;
        }
        .event-counter {
            font-size: 0.9em;
            color: var(--vscode-descriptionForeground);
            margin: 10px 0;
        }
        .loading {
            opacity: 0.6;
        }
    </style>
</head>
<body>
    <h1>📖 Scriptorium Reader</h1>
    <p>Read and display publications from Nostr relays</p>

    <div class="input-section">
        <div class="input-group">
            <label for="event-ref">Publication Reference:</label>
            <input type="text" id="event-ref" placeholder="nevent1..., naddr1..., hex ID, or kind:pubkey:d-tag" />
            <small style="color: var(--vscode-descriptionForeground); display: block; margin-top: 5px;">
                Enter nevent, naddr, hex event ID, or kind:pubkey:d-tag format
            </small>
        </div>
        <div class="input-group">
            <label for="relay-url">Relay URL:</label>
            <input type="text" id="relay-url" placeholder="wss://relay.example.com" />
            <small style="color: var(--vscode-descriptionForeground); display: block; margin-top: 5px;">
                Leave empty to use default relay from settings
            </small>
        </div>
        <button id="read-btn" onclick="readPublication()">📚 Read Publication</button>
    </div>

    <div id="status"></div>
    <div id="progress"></div>
    <div id="publication"></div>

    <script>
        const vscode = acquireVsCodeApi();

        // Load default relay from config
        vscode.postMessage({ command: 'getConfig' });

        function readPublication() {
            const eventRef = document.getElementById('event-ref').value.trim();
            const relayUrl = document.getElementById('relay-url').value.trim();

            if (!eventRef) {
                showStatus('Please enter a publication reference', 'error');
                return;
            }

            document.getElementById('read-btn').disabled = true;
            document.getElementById('read-btn').textContent = 'Loading...';

            vscode.postMessage({
                command: 'read',
                eventRef: eventRef,
                relayUrl: relayUrl || null
            });
        }

        let eventCount = 0;
        const eventsContainer = document.getElementById('publication');

        function showStatus(text, className) {
            const statusDiv = document.getElementById('status');
            statusDiv.innerHTML = '<div class="status ' + className + '">' + text + '</div>';
        }

        function showProgress(message, count) {
            const progressDiv = document.getElementById('progress');
            if (message) {
                progressDiv.innerHTML = '<div class="progress">' + escapeHtml(message) + (count ? ' <span class="event-counter">(' + count + ' events)</span>' : '') + '</div>';
            } else {
                progressDiv.innerHTML = '';
            }
        }

        function addEvent(event) {
            eventCount++;
            const pubDiv = document.getElementById('publication');
            
            // Initialize container if needed
            if (!pubDiv.querySelector('.publication')) {
                pubDiv.innerHTML = '<div class="publication"></div>';
            }
            
            const pubContainer = pubDiv.querySelector('.publication');
            
            // Find or create content section
            let contentSection = pubContainer.querySelector('.content-section');
            if (!contentSection) {
                contentSection = document.createElement('div');
                contentSection.className = 'content-section';
                contentSection.innerHTML = '<h2>📄 Content</h2><p class="event-counter" id="event-count">Events: ' + eventCount + '</p>';
                pubContainer.appendChild(contentSection);
            } else {
                const counter = contentSection.querySelector('#event-count');
                if (counter) {
                    counter.textContent = 'Events: ' + eventCount;
                }
            }
            
            // Extract d-tag
            let dtag = 'unknown';
            if (event.tags) {
                for (const tag of event.tags) {
                    if (tag && tag[0] === 'd' && tag[1]) {
                        dtag = tag[1];
                        break;
                    }
                }
            }
            
            // Create event element
            const eventDiv = document.createElement('div');
            eventDiv.className = 'content-item';
            eventDiv.innerHTML = '<div class="d-tag">d-tag: ' + escapeHtml(dtag) + '</div>' +
                                '<div class="content-body">' + escapeHtml(event.content || '(empty)') + '</div>';
            
            contentSection.appendChild(eventDiv);
            
            // Scroll to bottom
            eventDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        function renderPublication(publication) {
            const pubDiv = document.getElementById('publication');
            
            let html = '<div class="publication">';
            
            // Metadata
            if (publication.metadata) {
                html += '<div class="metadata">';
                html += '<h2>📋 Publication Metadata</h2>';
                
                const metadata = publication.metadata;
                if (metadata.title) {
                    html += '<div class="metadata-item"><span class="metadata-label">Title:</span> ' + escapeHtml(metadata.title) + '</div>';
                }
                if (metadata.author) {
                    html += '<div class="metadata-item"><span class="metadata-label">Author:</span> ' + escapeHtml(metadata.author) + '</div>';
                }
                if (metadata.language) {
                    html += '<div class="metadata-item"><span class="metadata-label">Language:</span> ' + escapeHtml(metadata.language) + '</div>';
                }
                if (metadata.summary) {
                    html += '<div class="metadata-item"><span class="metadata-label">Summary:</span> ' + escapeHtml(metadata.summary) + '</div>';
                }
                if (metadata.published_on) {
                    html += '<div class="metadata-item"><span class="metadata-label">Published On:</span> ' + escapeHtml(metadata.published_on) + '</div>';
                }
                if (metadata.published_by) {
                    html += '<div class="metadata-item"><span class="metadata-label">Published By:</span> ' + escapeHtml(metadata.published_by) + '</div>';
                }
                if (metadata.version) {
                    html += '<div class="metadata-item"><span class="metadata-label">Version:</span> ' + escapeHtml(metadata.version) + '</div>';
                }
                if (metadata.source) {
                    html += '<div class="metadata-item"><span class="metadata-label">Source:</span> <a href="' + escapeHtml(metadata.source) + '" target="_blank">' + escapeHtml(metadata.source) + '</a></div>';
                }
                if (metadata.image) {
                    html += '<div class="metadata-item"><span class="metadata-label">Image:</span> <img src="' + escapeHtml(metadata.image) + '" style="max-width: 200px; margin-top: 5px;" /></div>';
                }
                
                html += '</div>';
            }

            // Content
            html += '<div class="content-section">';
            html += '<h2>📄 Content</h2>';
            html += '<p class="event-counter">Total events: ' + (publication.total_events || eventCount) + '</p>';

            // Sort content events by d-tag for better organization
            const sortedDtags = Object.keys(publication.content_by_dtag || {}).sort();
            
            for (const dtag of sortedDtags) {
                const events = publication.content_by_dtag[dtag];
                for (const event of events) {
                    html += '<div class="content-item">';
                    html += '<div class="d-tag">d-tag: ' + escapeHtml(dtag) + '</div>';
                    html += '<div class="content-body">' + escapeHtml(event.content || '(empty)') + '</div>';
                    html += '</div>';
                }
            }

            // If no organized content, show all content events
            if (sortedDtags.length === 0 && publication.content_events) {
                for (const event of publication.content_events) {
                    let dtag = 'unknown';
                    // Try to find d-tag in event tags
                    if (event.tags) {
                        for (const tag of event.tags) {
                            if (tag && tag[0] === 'd' && tag[1]) {
                                dtag = tag[1];
                                break;
                            }
                        }
                    }
                    html += '<div class="content-item">';
                    html += '<div class="d-tag">d-tag: ' + escapeHtml(dtag) + '</div>';
                    html += '<div class="content-body">' + escapeHtml(event.content || '(empty)') + '</div>';
                    html += '</div>';
                }
            }

            html += '</div>';
            html += '</div>';

            pubDiv.innerHTML = html;
            eventCount = publication.total_events || 0;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        window.addEventListener('message', event => {
            const message = event.data;
            
            if (message.type === 'status') {
                showStatus(message.text, message.class);
                if (message.class === 'success' || message.class === 'error') {
                    document.getElementById('read-btn').disabled = false;
                    document.getElementById('read-btn').textContent = '📚 Read Publication';
                    showProgress('', 0);
                }
            } else if (message.type === 'progress') {
                showProgress(message.message, message.count || eventCount);
            } else if (message.type === 'event') {
                addEvent(message.event);
                showProgress('Fetching events...', message.count || eventCount);
            } else if (message.type === 'publication') {
                renderPublication(message.publication);
            } else if (message.type === 'clear') {
                eventCount = 0;
                document.getElementById('publication').innerHTML = '';
                showProgress('', 0);
            } else if (message.type === 'config') {
                if (!document.getElementById('relay-url').value && message.relayUrl) {
                    document.getElementById('relay-url').value = message.relayUrl;
                }
            }
        });

        // Allow Enter key to trigger read
        document.getElementById('event-ref').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                readPublication();
            }
        });
        document.getElementById('relay-url').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                readPublication();
            }
        });
    </script>
</body>
</html>`;
    }
}

