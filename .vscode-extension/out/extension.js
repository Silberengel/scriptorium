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
exports.activate = activate;
exports.findPythonCommand = findPythonCommand;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const util_1 = require("util");
const path_1 = require("path");
const fs_1 = require("fs");
const panel_1 = require("./panel");
const treeProvider_1 = require("./treeProvider");
const readerPanel_1 = require("./readerPanel");
const execAsync = (0, util_1.promisify)(child_process_1.exec);
function activate(context) {
    console.log('Scriptorium Publisher extension is now active!');
    const provider = new treeProvider_1.ScriptoriumProvider(context.extensionPath);
    // Use createTreeView which returns a disposable
    const treeView = vscode.window.createTreeView('scriptoriumEvents', {
        treeDataProvider: provider
    });
    context.subscriptions.push(treeView);
    // Open panel command
    const openPanelCommand = vscode.commands.registerCommand('scriptorium.openPanel', () => {
        panel_1.ScriptoriumPanel.createOrShow(context.extensionPath);
    });
    // Open settings command
    const openSettingsCommand = vscode.commands.registerCommand('scriptorium.openSettings', () => {
        vscode.commands.executeCommand('workbench.action.openSettings', '@ext:silberengel.scriptorium-publisher');
    });
    // Initialize metadata
    const initMetadataCommand = vscode.commands.registerCommand('scriptorium.initMetadata', async (uri) => {
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
        const hasCollection = await vscode.window.showQuickPick(['Yes', 'No'], { placeHolder: 'Does this source have a collection (top-level index)?' });
        if (hasCollection === undefined) {
            return;
        }
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
            }
            else {
                vscode.window.showErrorMessage(`Failed to initialize metadata: ${output.error}`);
            }
        });
    });
    // Generate events
    const generateCommand = vscode.commands.registerCommand('scriptorium.generate', async (uri) => {
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
        const sourceType = config.get('sourceType', 'HTML');
        const options = {
            input: filePath,
            sourceType: sourceType
        };
        // Show options dialog
        const promoteStructure = await vscode.window.showQuickPick(['Yes', 'No'], { placeHolder: 'Promote default structure (chapters/verses)?' });
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
            }
            else {
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
        const relayUrl = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
        let secretKey = config.get('secretKey', '');
        if (!secretKey && !process.env.SCRIPTORIUM_KEY) {
            const input = await vscode.window.showInputBox({
                prompt: 'Enter your Nostr secret key (nsec or hex)',
                password: true,
                placeHolder: 'nsec1... or hex key',
                ignoreFocusOut: true
            });
            if (!input) {
                return;
            }
            await config.update('secretKey', input, vscode.ConfigurationTarget.Global);
            secretKey = input;
        }
        const confirm = await vscode.window.showWarningMessage(`Publish events to ${relayUrl}?`, { modal: true }, 'Publish', 'Cancel');
        if (confirm !== 'Publish') {
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Publishing events...",
            cancellable: false
        }, async (progress) => {
            progress.report({ increment: 0, message: "Connecting to relay..." });
            const output = await runCommand('publish', {});
            if (output.success) {
                vscode.window.showInformationMessage(`Published to ${relayUrl} successfully!`);
            }
            else {
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
        const republish = await vscode.window.showQuickPick(['Check only', 'Check and republish missing'], { placeHolder: 'What would you like to do?' });
        if (republish === undefined) {
            return;
        }
        const output = await runCommand('qc', {
            republish: republish === 'Check and republish missing'
        });
        if (output.success) {
            vscode.window.showInformationMessage('QC check completed!');
        }
        else {
            vscode.window.showWarningMessage(`QC check found issues: ${output.error}`);
        }
    });
    // Generate & Publish All
    const allCommand = vscode.commands.registerCommand('scriptorium.all', async (uri) => {
        const filePath = uri?.fsPath || await getActiveFilePath();
        if (!filePath) {
            vscode.window.showErrorMessage('Please open a file or select one in the explorer');
            return;
        }
        const config = vscode.workspace.getConfiguration('scriptorium');
        const sourceType = config.get('sourceType', 'HTML');
        const output = await runCommand('all', {
            input: filePath,
            sourceType: sourceType
        });
        if (output.success) {
            vscode.window.showInformationMessage('Generate and publish completed!');
            provider.refresh();
        }
        else {
            vscode.window.showErrorMessage(`Failed: ${output.error}`);
        }
    });
    // Broadcast publication
    const broadcastCommand = vscode.commands.registerCommand('scriptorium.broadcast', async () => {
        const nevent = await vscode.window.showInputBox({
            prompt: 'Enter nevent, naddr, or hex event ID',
            placeHolder: 'nevent1... or naddr1... or hex ID'
        });
        if (!nevent) {
            return;
        }
        const config = vscode.workspace.getConfiguration('scriptorium');
        const relayUrl = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
        await runScript('broadcast_publication', [nevent, relayUrl]);
    });
    // Delete publication
    const deleteCommand = vscode.commands.registerCommand('scriptorium.delete', async () => {
        const nevent = await vscode.window.showInputBox({
            prompt: 'Enter nevent, naddr, or hex event ID',
            placeHolder: 'nevent1... or naddr1... or hex ID'
        });
        if (!nevent) {
            return;
        }
        const config = vscode.workspace.getConfiguration('scriptorium');
        const relayUrl = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
        const confirm = await vscode.window.showWarningMessage('Are you sure you want to delete this publication?', { modal: true }, 'Delete');
        if (confirm !== 'Delete') {
            return;
        }
        await runScript('delete_publication', [nevent, relayUrl]);
    });
    // Read publication
    const readCommand = vscode.commands.registerCommand('scriptorium.read', async () => {
        const config = vscode.workspace.getConfiguration('scriptorium');
        const defaultRelay = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
        // Open reader panel first
        const panel = readerPanel_1.ReaderPanel.createOrShow(context.extensionPath);
        // Show input dialog for event reference
        const eventRef = await vscode.window.showInputBox({
            prompt: 'Enter publication reference (nevent, naddr, hex ID, or kind:pubkey:d-tag)',
            placeHolder: 'nevent1..., naddr1..., hex ID, or 30040:pubkey:d-tag'
        });
        if (!eventRef) {
            return;
        }
        // Ask for relay URL (optional, will use default if empty)
        const relayUrlInput = await vscode.window.showInputBox({
            prompt: 'Enter relay URL (leave empty to use default from settings)',
            placeHolder: defaultRelay,
            value: defaultRelay
        });
        const relayUrl = relayUrlInput || defaultRelay;
        // Trigger read in panel
        panel.triggerRead(eventRef, relayUrl);
    });
    // Add file to input directory
    const addFileCommand = vscode.commands.registerCommand('scriptorium.addFile', async () => {
        const config = vscode.workspace.getConfiguration('scriptorium');
        const inputDir = config.get('inputDir', 'uploader/input_data');
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
            vscode.window.showErrorMessage('No workspace folder open');
            return;
        }
        // Show file picker
        const selected = await vscode.window.showOpenDialog({
            canSelectFiles: true,
            canSelectFolders: false,
            canSelectMany: true,
            filters: {
                'Source Files': ['html', 'adoc', 'md', 'rtf', 'epub'],
                'All Files': ['*']
            },
            title: 'Select files to add to input directory'
        });
        if (!selected || selected.length === 0) {
            return;
        }
        const inputPath = vscode.Uri.joinPath(workspaceFolder.uri, inputDir);
        // Ensure input directory exists
        try {
            await vscode.workspace.fs.createDirectory(inputPath);
        }
        catch {
            // Directory might already exist
        }
        // Copy files
        let successCount = 0;
        for (const fileUri of selected) {
            try {
                const fileName = fileUri.path.split('/').pop() || fileUri.path.split('\\').pop() || 'file';
                const destUri = vscode.Uri.joinPath(inputPath, fileName);
                await vscode.workspace.fs.copy(fileUri, destUri, { overwrite: true });
                successCount++;
            }
            catch (error) {
                vscode.window.showErrorMessage(`Failed to copy ${fileUri.fsPath}: ${error.message}`);
            }
        }
        if (successCount > 0) {
            vscode.window.showInformationMessage(`Added ${successCount} file(s) to ${inputDir}`);
            // Refresh the panel if it's open
            panel_1.ScriptoriumPanel.currentPanel?.refreshFileList();
        }
    });
    // Open input folder
    const openInputFolderCommand = vscode.commands.registerCommand('scriptorium.openInputFolder', async () => {
        const config = vscode.workspace.getConfiguration('scriptorium');
        const inputDir = config.get('inputDir', 'uploader/input_data');
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
            vscode.window.showErrorMessage('No workspace folder open');
            return;
        }
        const inputPath = vscode.Uri.joinPath(workspaceFolder.uri, inputDir);
        // Ensure directory exists
        try {
            await vscode.workspace.fs.createDirectory(inputPath);
        }
        catch {
            // Directory might already exist
        }
        // Open in explorer
        vscode.commands.executeCommand('revealFileInOS', inputPath);
    });
    // Browse for input directory
    const browseInputDirCommand = vscode.commands.registerCommand('scriptorium.browseInputDir', async () => {
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (!workspaceFolder) {
            vscode.window.showErrorMessage('No workspace folder open');
            return;
        }
        // Show folder picker
        const selected = await vscode.window.showOpenDialog({
            canSelectFiles: false,
            canSelectFolders: true,
            canSelectMany: false,
            openLabel: 'Select Input Directory',
            title: 'Select input directory for source files'
        });
        if (!selected || selected.length === 0) {
            return;
        }
        const selectedPath = selected[0];
        const workspacePath = workspaceFolder.uri;
        // Calculate relative path from workspace root
        let relativePath;
        if (selectedPath.path.startsWith(workspacePath.path)) {
            // Selected folder is within workspace
            relativePath = selectedPath.path.substring(workspacePath.path.length + 1);
        }
        else {
            // Selected folder is outside workspace - show error
            vscode.window.showErrorMessage('Selected folder must be within the workspace');
            return;
        }
        // Update setting
        const config = vscode.workspace.getConfiguration('scriptorium');
        await config.update('inputDir', relativePath, vscode.ConfigurationTarget.Workspace);
        vscode.window.showInformationMessage(`Input directory set to: ${relativePath}`);
    });
    context.subscriptions.push(openPanelCommand, openSettingsCommand, initMetadataCommand, generateCommand, publishCommand, qcCommand, allCommand, broadcastCommand, deleteCommand, readCommand, addFileCommand, openInputFolderCommand, browseInputDirCommand);
}
async function getActiveFilePath() {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        return editor.document.uri.fsPath;
    }
    return undefined;
}
async function findPythonCommand() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    // Check for virtual environment first
    if (workspaceFolder) {
        const venvPath = (0, path_1.join)(workspaceFolder.uri.fsPath, '.venv', 'bin', 'python3');
        if ((0, fs_1.existsSync)(venvPath)) {
            // Verify it works
            try {
                await execAsync(`"${venvPath}" --version`);
                return venvPath;
            }
            catch {
                // Venv exists but doesn't work, continue to other options
            }
        }
    }
    // Try python3 first (common on Linux/Mac), then python
    try {
        await execAsync('python3 --version');
        return 'python3';
    }
    catch {
        try {
            await execAsync('python --version');
            return 'python';
        }
        catch {
            // Fallback - let the error happen with a clear message
            return 'python3';
        }
    }
}
async function runCommand(cmd, options) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        return { success: false, error: 'No workspace folder open' };
    }
    const config = vscode.workspace.getConfiguration('scriptorium');
    const secretKey = config.get('secretKey', '');
    const relayUrl = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
    const env = { ...process.env };
    if (secretKey) {
        env.SCRIPTORIUM_KEY = secretKey;
    }
    env.SCRIPTORIUM_RELAY = relayUrl;
    const args = [cmd];
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
    }
    catch (error) {
        const errorMsg = error.stderr || error.message || String(error);
        return { success: false, error: errorMsg, output: error.stdout };
    }
}
async function runScript(script, args) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        vscode.window.showErrorMessage('No workspace folder open');
        return;
    }
    const config = vscode.workspace.getConfiguration('scriptorium');
    const secretKey = config.get('secretKey', '');
    const relayUrl = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
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
        }
        catch (error) {
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
function deactivate() {
    // Cleanup is handled by VS Code through context.subscriptions
}
//# sourceMappingURL=extension.js.map