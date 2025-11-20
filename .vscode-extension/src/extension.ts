import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import { join } from 'path';
import { ScriptoriumPanel } from './panel';
import { ScriptoriumProvider } from './treeProvider';

const execAsync = promisify(exec);

export function activate(context: vscode.ExtensionContext) {
    console.log('Scriptorium Publisher extension is now active!');

    const provider = new ScriptoriumProvider(context.extensionPath);
    vscode.window.registerTreeDataProvider('scriptoriumEvents', provider);

    // Open panel command
    const openPanelCommand = vscode.commands.registerCommand('scriptorium.openPanel', () => {
        ScriptoriumPanel.createOrShow(context.extensionPath);
    });

    // Open settings command
    const openSettingsCommand = vscode.commands.registerCommand('scriptorium.openSettings', () => {
        vscode.commands.executeCommand('workbench.action.openSettings', '@ext:silberengel.scriptorium-publisher');
    });

    // Initialize metadata
    const initMetadataCommand = vscode.commands.registerCommand('scriptorium.initMetadata', async (uri?: vscode.Uri) => {
        let filePath = uri?.fsPath || await getActiveFilePath();
        
        // If no file selected, show file picker
        if (!filePath) {
            const selected = await vscode.window.showOpenDialog({
                canSelectFiles: true,
                canSelectFolders: false,
                canSelectMany: false,
                filters: {
                    'Source Files': ['html', 'adoc', 'md']
                },
                title: 'Select source file for metadata initialization'
            });
            if (!selected || selected.length === 0) {
                return;
            }
            filePath = selected[0].fsPath;
        }

        const hasCollection = await vscode.window.showQuickPick(
            ['Yes', 'No'],
            { placeHolder: 'Does this source have a collection (top-level index)?' }
        );

        if (hasCollection === undefined) { return; }

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Initializing metadata...",
            cancellable: false
        }, async (progress) => {
            const output = await runCommand('init-metadata', {
                input: filePath,
                hasCollection: hasCollection === 'Yes'
            });

            if (output.success) {
                vscode.window.showInformationMessage('Metadata initialized successfully!');
                provider.refresh();
            } else {
                vscode.window.showErrorMessage(`Failed to initialize metadata: ${output.error}`);
            }
        });
    });

    // Generate events
    const generateCommand = vscode.commands.registerCommand('scriptorium.generate', async (uri?: vscode.Uri) => {
        let filePath = uri?.fsPath || await getActiveFilePath();
        
        // If no file selected, show file picker
        if (!filePath) {
            const selected = await vscode.window.showOpenDialog({
                canSelectFiles: true,
                canSelectFolders: false,
                canSelectMany: false,
                filters: {
                    'Source Files': ['html', 'adoc', 'md']
                },
                title: 'Select source file to generate events'
            });
            if (!selected || selected.length === 0) {
                return;
            }
            filePath = selected[0].fsPath;
        }

        const config = vscode.workspace.getConfiguration('scriptorium');
        const sourceType = config.get<string>('sourceType', 'HTML');

        const options: any = {
            input: filePath,
            sourceType: sourceType
        };

        // Show options dialog
        const promoteStructure = await vscode.window.showQuickPick(
            ['Yes', 'No'],
            { placeHolder: 'Promote default structure (chapters/verses)?' }
        );
        if (promoteStructure === 'Yes') {
            options.promoteDefaultStructure = true;
        }

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Generating events...",
            cancellable: false
        }, async (progress) => {
            progress.report({ increment: 0, message: "Parsing source file..." });
            
            const output = await runCommand('generate', options);

            if (output.success) {
                vscode.window.showInformationMessage(`Generated ${output.eventCount || 0} events successfully!`);
                provider.refresh();
            } else {
                vscode.window.showErrorMessage(`Failed to generate events: ${output.error}`);
                // Show output channel with details
                const outputChannel = vscode.window.createOutputChannel('Scriptorium');
                outputChannel.appendLine('Generate command failed:');
                outputChannel.appendLine(output.error || 'Unknown error');
                if (output.output) {
                    outputChannel.appendLine('\nOutput:');
                    outputChannel.appendLine(output.output);
                }
                outputChannel.show();
            }
        });
    });

    // Publish events
    const publishCommand = vscode.commands.registerCommand('scriptorium.publish', async () => {
        const config = vscode.workspace.getConfiguration('scriptorium');
        const relayUrl = config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com');
        let secretKey = config.get<string>('secretKey', '');

        if (!secretKey && !process.env.SCRIPTORIUM_KEY) {
            const input = await vscode.window.showInputBox({
                prompt: 'Enter your Nostr secret key (nsec or hex)',
                password: true,
                placeHolder: 'nsec1... or hex key',
                ignoreFocusOut: true
            });
            if (!input) { return; }
            await config.update('secretKey', input, vscode.ConfigurationTarget.Global);
            secretKey = input;
        }

        const confirm = await vscode.window.showWarningMessage(
            `Publish events to ${relayUrl}?`,
            { modal: true },
            'Publish',
            'Cancel'
        );
        if (confirm !== 'Publish') { return; }

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Publishing events...",
            cancellable: false
        }, async (progress) => {
            progress.report({ increment: 0, message: "Connecting to relay..." });
            
            const output = await runCommand('publish', {});

            if (output.success) {
                vscode.window.showInformationMessage(`Published to ${relayUrl} successfully!`);
            } else {
                vscode.window.showErrorMessage(`Failed to publish: ${output.error}`);
                // Show output channel with details
                const outputChannel = vscode.window.createOutputChannel('Scriptorium');
                outputChannel.appendLine('Publish command failed:');
                outputChannel.appendLine(output.error || 'Unknown error');
                if (output.output) {
                    outputChannel.appendLine('\nOutput:');
                    outputChannel.appendLine(output.output);
                }
                outputChannel.show();
            }
        });
    });

    // Quality control
    const qcCommand = vscode.commands.registerCommand('scriptorium.qc', async () => {
        const republish = await vscode.window.showQuickPick(
            ['Check only', 'Check and republish missing'],
            { placeHolder: 'What would you like to do?' }
        );

        if (republish === undefined) { return; }

        const output = await runCommand('qc', {
            republish: republish === 'Check and republish missing'
        });

        if (output.success) {
            vscode.window.showInformationMessage('QC check completed!');
        } else {
            vscode.window.showWarningMessage(`QC check found issues: ${output.error}`);
        }
    });

    // Generate & Publish All
    const allCommand = vscode.commands.registerCommand('scriptorium.all', async (uri?: vscode.Uri) => {
        const filePath = uri?.fsPath || await getActiveFilePath();
        if (!filePath) {
            vscode.window.showErrorMessage('Please open a file or select one in the explorer');
            return;
        }

        const config = vscode.workspace.getConfiguration('scriptorium');
        const sourceType = config.get<string>('sourceType', 'HTML');

        const output = await runCommand('all', {
            input: filePath,
            sourceType: sourceType
        });

        if (output.success) {
            vscode.window.showInformationMessage('Generate and publish completed!');
            provider.refresh();
        } else {
            vscode.window.showErrorMessage(`Failed: ${output.error}`);
        }
    });

    // Broadcast publication
    const broadcastCommand = vscode.commands.registerCommand('scriptorium.broadcast', async () => {
        const nevent = await vscode.window.showInputBox({
            prompt: 'Enter nevent, naddr, or hex event ID',
            placeHolder: 'nevent1... or naddr1... or hex ID'
        });
        if (!nevent) { return; }

        const config = vscode.workspace.getConfiguration('scriptorium');
        const relayUrl = config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com');

        await runScript('broadcast_publication', [nevent, relayUrl]);
    });

    // Delete publication
    const deleteCommand = vscode.commands.registerCommand('scriptorium.delete', async () => {
        const nevent = await vscode.window.showInputBox({
            prompt: 'Enter nevent, naddr, or hex event ID',
            placeHolder: 'nevent1... or naddr1... or hex ID'
        });
        if (!nevent) { return; }

        const config = vscode.workspace.getConfiguration('scriptorium');
        const relayUrl = config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com');

        const confirm = await vscode.window.showWarningMessage(
            'Are you sure you want to delete this publication?',
            { modal: true },
            'Delete'
        );
        if (confirm !== 'Delete') { return; }

        await runScript('delete_publication', [nevent, relayUrl]);
    });

    context.subscriptions.push(
        openPanelCommand,
        openSettingsCommand,
        initMetadataCommand,
        generateCommand,
        publishCommand,
        qcCommand,
        allCommand,
        broadcastCommand,
        deleteCommand
    );
}

async function getActiveFilePath(): Promise<string | undefined> {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        return editor.document.uri.fsPath;
    }
    return undefined;
}

async function findPythonCommand(): Promise<string> {
    // Try python3 first (common on Linux/Mac), then python
    try {
        await execAsync('python3 --version');
        return 'python3';
    } catch {
        try {
            await execAsync('python --version');
            return 'python';
        } catch {
            // Fallback - let the error happen with a clear message
            return 'python3';
        }
    }
}

async function runCommand(cmd: string, options: any): Promise<{ success: boolean; error?: string; eventCount?: number; output?: string }> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        return { success: false, error: 'No workspace folder open' };
    }

    const config = vscode.workspace.getConfiguration('scriptorium');
    const secretKey = config.get<string>('secretKey', '');
    const relayUrl = config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com');

    const env = { ...process.env };
    if (secretKey) {
        env.SCRIPTORIUM_KEY = secretKey;
    }
    env.SCRIPTORIUM_RELAY = relayUrl;

    const args: string[] = [cmd];
    if (options.input) {
        args.push('--input', options.input);
    }
    if (options.sourceType) {
        args.push('--source-type', options.sourceType);
    }
    if (options.hasCollection) {
        args.push('--has-collection');
    }
    if (options.promoteDefaultStructure) {
        args.push('--promote-default-structure');
    }
    if (options.republish) {
        args.push('--republish');
    }

    const pythonCmd = await findPythonCommand();
    const command = `${pythonCmd} -m uploader.publisher.cli ${args.join(' ')}`;
    
    try {
        const { stdout, stderr } = await execAsync(command, {
            cwd: workspaceFolder.uri.fsPath,
            env
        });

        // Try to parse event count from output
        const eventCountMatch = stdout.match(/Total events: (\d+)/);
        const eventCount = eventCountMatch ? parseInt(eventCountMatch[1]) : undefined;

        return { success: true, eventCount, output: stdout };
    } catch (error: any) {
        const errorMsg = error.stderr || error.message || String(error);
        return { success: false, error: errorMsg, output: error.stdout };
    }
}

async function runScript(script: string, args: string[]): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        vscode.window.showErrorMessage('No workspace folder open');
        return;
    }

    const config = vscode.workspace.getConfiguration('scriptorium');
    const secretKey = config.get<string>('secretKey', '');
    const relayUrl = config.get<string>('relayUrl', 'wss://thecitadel.nostr1.com');

    const env = { ...process.env };
    if (secretKey) {
        env.SCRIPTORIUM_KEY = secretKey;
    }
    env.SCRIPTORIUM_RELAY = relayUrl;

    const pythonCmd = await findPythonCommand();
    const command = `${pythonCmd} -m uploader.publisher.scripts.${script} ${args.join(' ')}`;
    
    vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `Running ${script}...`,
        cancellable: false
    }, async (progress) => {
        try {
            const { stdout, stderr } = await execAsync(command, {
                cwd: workspaceFolder.uri.fsPath,
                env
            });
            vscode.window.showInformationMessage('Script completed successfully');
            
            // Show output in output channel
            const outputChannel = vscode.window.createOutputChannel('Scriptorium');
            outputChannel.appendLine(`=== ${script} output ===`);
            outputChannel.appendLine(stdout);
            if (stderr) {
                outputChannel.appendLine(`\nErrors:`);
                outputChannel.appendLine(stderr);
            }
            outputChannel.show();
        } catch (error: any) {
            vscode.window.showErrorMessage(`Script failed: ${error.message}`);
            const outputChannel = vscode.window.createOutputChannel('Scriptorium');
            outputChannel.appendLine(`=== ${script} error ===`);
            outputChannel.appendLine(error.message);
            if (error.stdout) {
                outputChannel.appendLine('\nOutput:');
                outputChannel.appendLine(error.stdout);
            }
            if (error.stderr) {
                outputChannel.appendLine('\nErrors:');
                outputChannel.appendLine(error.stderr);
            }
            outputChannel.show();
        }
    });
}

export function deactivate() {}

