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
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const util_1 = require("util");
const panel_1 = require("./panel");
const treeProvider_1 = require("./treeProvider");
const execAsync = (0, util_1.promisify)(child_process_1.exec);
function activate(context) {
    console.log('Scriptorium Publisher extension is now active!');
    const provider = new treeProvider_1.ScriptoriumProvider(context.extensionPath);
    vscode.window.registerTreeDataProvider('scriptoriumEvents', provider);
    // Open panel command
    const openPanelCommand = vscode.commands.registerCommand('scriptorium.openPanel', () => {
        panel_1.ScriptoriumPanel.createOrShow(context.extensionPath);
    });
    // Initialize metadata
    const initMetadataCommand = vscode.commands.registerCommand('scriptorium.initMetadata', async (uri) => {
        const filePath = uri?.fsPath || await getActiveFilePath();
        if (!filePath) {
            vscode.window.showErrorMessage('Please open a file or select one in the explorer');
            return;
        }
        const config = vscode.workspace.getConfiguration('scriptorium');
        const hasCollection = await vscode.window.showQuickPick(['Yes', 'No'], { placeHolder: 'Does this source have a collection (top-level index)?' });
        if (hasCollection === undefined) {
            return;
        }
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
    // Generate events
    const generateCommand = vscode.commands.registerCommand('scriptorium.generate', async (uri) => {
        const filePath = uri?.fsPath || await getActiveFilePath();
        if (!filePath) {
            vscode.window.showErrorMessage('Please open a file or select one in the explorer');
            return;
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
        const output = await runCommand('generate', options);
        if (output.success) {
            vscode.window.showInformationMessage(`Generated ${output.eventCount || 0} events successfully!`);
            provider.refresh();
        }
        else {
            vscode.window.showErrorMessage(`Failed to generate events: ${output.error}`);
        }
    });
    // Publish events
    const publishCommand = vscode.commands.registerCommand('scriptorium.publish', async () => {
        const config = vscode.workspace.getConfiguration('scriptorium');
        const relayUrl = config.get('relayUrl', 'wss://thecitadel.nostr1.com');
        const secretKey = config.get('secretKey', '');
        if (!secretKey && !process.env.SCRIPTORIUM_KEY) {
            const input = await vscode.window.showInputBox({
                prompt: 'Enter your Nostr secret key (nsec or hex)',
                password: true,
                placeHolder: 'nsec1... or hex key'
            });
            if (!input) {
                return;
            }
            await config.update('secretKey', input, vscode.ConfigurationTarget.Global);
        }
        const output = await runCommand('publish', {});
        if (output.success) {
            vscode.window.showInformationMessage(`Published to ${relayUrl} successfully!`);
        }
        else {
            vscode.window.showErrorMessage(`Failed to publish: ${output.error}`);
        }
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
    context.subscriptions.push(openPanelCommand, initMetadataCommand, generateCommand, publishCommand, qcCommand, allCommand, broadcastCommand, deleteCommand);
}
async function getActiveFilePath() {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        return editor.document.uri.fsPath;
    }
    return undefined;
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
    const command = `python -m uploader.publisher.cli ${args.join(' ')}`;
    try {
        const { stdout, stderr } = await execAsync(command, {
            cwd: workspaceFolder.uri.fsPath,
            env
        });
        // Try to parse event count from output
        const eventCountMatch = stdout.match(/Total events: (\d+)/);
        const eventCount = eventCountMatch ? parseInt(eventCountMatch[1]) : undefined;
        return { success: true, eventCount };
    }
    catch (error) {
        return { success: false, error: error.message || String(error) };
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
    const env = { ...process.env };
    if (secretKey) {
        env.SCRIPTORIUM_KEY = secretKey;
    }
    const command = `python -m uploader.publisher.scripts.${script} ${args.join(' ')}`;
    try {
        const { stdout } = await execAsync(command, {
            cwd: workspaceFolder.uri.fsPath,
            env
        });
        vscode.window.showInformationMessage('Script completed successfully');
    }
    catch (error) {
        vscode.window.showErrorMessage(`Script failed: ${error.message}`);
    }
}
function deactivate() { }
//# sourceMappingURL=extension.js.map