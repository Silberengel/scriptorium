import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

export class ScriptoriumProvider implements vscode.TreeDataProvider<EventItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<EventItem | undefined | null | void> = new vscode.EventEmitter<EventItem | undefined | null | void>();
    readonly onDidChangeTreeData: vscode.Event<EventItem | undefined | null | void> = this._onDidChangeTreeData.event;

    constructor(private extensionPath: string) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: EventItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: EventItem): Thenable<EventItem[]> {
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
            return Promise.resolve([]);
        }

        if (!element) {
            // Root level - show summary
            const config = vscode.workspace.getConfiguration('scriptorium');
            const outDir = config.get<string>('outputDir', 'uploader/publisher/out');
            const eventsPath = path.join(workspaceFolder.uri.fsPath, outDir, 'events', 'events.ndjson');
            const cachePath = path.join(workspaceFolder.uri.fsPath, outDir, 'cache', 'event_index.json');

            const items: EventItem[] = [];

            if (fs.existsSync(eventsPath)) {
                try {
                    const content = fs.readFileSync(eventsPath, 'utf-8');
                    const eventCount = content.split('\n').filter(line => line.trim()).length;
                    items.push(new EventItem(
                        `Events: ${eventCount}`,
                        vscode.TreeItemCollapsibleState.None,
                        eventsPath
                    ));
                } catch (e) {
                    // Ignore
                }
            }

            if (fs.existsSync(cachePath)) {
                try {
                    const content = JSON.parse(fs.readFileSync(cachePath, 'utf-8'));
                    items.push(new EventItem(
                        `Index: ${content.count || 0} d-tags`,
                        vscode.TreeItemCollapsibleState.None,
                        cachePath
                    ));
                } catch (e) {
                    // Ignore
                }
            }

            if (items.length === 0) {
                items.push(new EventItem(
                    'No events generated yet',
                    vscode.TreeItemCollapsibleState.None
                ));
            }

            return Promise.resolve(items);
        }

        return Promise.resolve([]);
    }
}

class EventItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly filePath?: string
    ) {
        super(label, collapsibleState);

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

