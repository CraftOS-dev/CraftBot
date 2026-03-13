"""CSS styles for the TUI interface."""

TUI_CSS = """
Screen {
    layout: vertical;
    background: #000000;
    color: #e5e5e5;
}

/* Shared chrome */
#top-region {
    height: 1fr;
    min-width: 0;
}

#chat-panel, #action-panel {
    height: 100%;
    border: solid #2a2a2a;
    border-title-align: left;
    border-title-color: #a0a0a0;
    background: #000000;
    margin: 0 1;
    min-width: 0;  /* allow panels to shrink with the terminal */
}

#chat-log, #action-log {
    text-wrap: wrap;
    text-overflow: fold;
    overflow-x: hidden;
    min-width: 0;  /* enable reflow instead of clamped min-content width */
    background: #000000;
}

#chat-panel {
    width: 2fr;
}

#right-panel {
    width: 1fr;
    height: 100%;
    layout: vertical;
}

#vm-footage-panel {
    height: 1fr;
    min-height: 8;
    border: solid #2a2a2a;
    border-title-align: left;
    border-title-color: #ff4f18;
    background: #0a0a0a;
    margin: 0 1;
}

#vm-footage-panel.-hidden {
    display: none;
    height: 0;
    min-height: 0;
}

#action-panel {
    height: 1fr;
}

TextLog {
    height: 1fr;
    padding: 0 1;
    overflow-x: hidden;
    background: #000000;
}

#bottom-region {
    height: auto;
    border-top: solid #1a1a1a;
    padding: 0;
    background: #000000;
}

#status-bar {
    height: 1;
    min-height: 1;
    text-wrap: nowrap;
    overflow: hidden;
    text-style: bold;
    color: #a0a0a0;
    background: #000000;
    padding: 0 1;
}

#chat-input {
    border: solid #2a2a2a;
    background: #0a0a0a;
    color: #e5e5e5;
    margin: 0 1;
}

#chat-input:focus {
    border: solid #ff4f18;
}

/* Menu layer */
#menu-layer {
    align: center middle;
    content-align: center middle;
    background: #000000;
}

#menu-panel {
    width: 92;
    max-width: 100%;
    max-height: 95%;
    border: none;
    background: #000000;
    padding: 3 5;
    content-align: center middle;
    overflow: auto;
}

#menu-panel.-hidden {
    display: none;
}

#menu-header {
    text-style: bold;
    content-align: center middle;
    width: 100%;
    margin-bottom: 1;
}

#menu-copy {
    color: #a0a0a0;
    margin-bottom: 1;
}

#provider-hint {
    color: #a0a0a0;
    text-style: bold;
}

#menu-hint {
    color: #666666;
}

#menu-hint.-warning {
    color: #ff8c00;
}

#menu-hint.-ready {
    color: #00cc00;
}

/* Command-prompt style options */
#menu-options {
    width: 24;
    height: auto;
    margin-top: 1;
    content-align: center middle;
    background: transparent;
    border: none;
}

#menu-options > ListItem {
    padding: 0 0;
}

/* Default item text */
.menu-item {
    color: #a0a0a0;
}

/* Highlight for list selections */
#menu-options > ListItem.--highlight .menu-item,
#provider-options > ListItem.--highlight .menu-item,
#settings-actions-list > ListItem.--highlight .menu-item {
    background: #ff4f18;
    color: #ffffff;
    text-style: bold;
}

/* Provider options list in settings */
#provider-options {
    width: 28;
    height: auto;
    margin: 1 0;
    background: transparent;
    border: none;
}

#provider-options > ListItem {
    padding: 0 0;
}

/* Settings card */
#settings-card {
    max-width: 100%;
    height: 100%;
    border: none;
    background: #000000;
    padding: 2 3 3 3;
    content-align: center top;
    overflow: auto;
    layout: vertical;
}

/* Settings tab bar */
#settings-tab-bar {
    height: auto;
    margin-bottom: 1;
}

/* Tab button styling */
.settings-tab {
    width: auto;
    min-width: 12;
    height: 1;
    background: #1a1a1a;
    color: #666666;
    border: none;
    margin-right: 1;
}

.settings-tab:hover {
    background: #2a2a2a;
    color: #a0a0a0;
}

.settings-tab.-active {
    background: #ff4f18;
    color: #ffffff;
}

/* Settings sections */
#section-models, #section-mcp, #section-skills, #section-integrations {
    height: auto;
    padding: 1 0;
}

#section-models.-hidden, #section-mcp.-hidden, #section-skills.-hidden, #section-integrations.-hidden {
    display: none;
}

#settings-card Static {
    color: #a0a0a0;
}

#settings-title {
    text-style: bold;
    color: #ffffff;
    margin-bottom: 1;
}

#settings-card Input {
    width: 100%;
    border: solid #2a2a2a;
    background: #0a0a0a;
    color: #e5e5e5;
}

#settings-card Input:focus {
    border: solid #ff4f18;
}

#model-display {
    color: #ff4f18;
    text-style: bold;
    margin-top: 1;
}

#api-key-label {
    margin-top: 1;
}

/* Settings actions styled like a prompt list */
#settings-actions-list {
    width: 24;
    height: auto;
    margin-top: 1;
    content-align: center middle;
    background: transparent;
    border: none;
}

#settings-actions-list > ListItem {
    padding: 0 0;
}

#chat-layer.-hidden,
#menu-layer.-hidden {
    display: none;
}



/* MCP Server list - standardized with integration style */
#mcp-server-list {
    height: auto;
    max-height: 15;
    margin: 1 0;
    border: solid #2a2a2a;
    background: #0a0a0a;
    padding: 1;
}

.mcp-server-row {
    height: 1;
    margin-bottom: 1;
}

.mcp-server-name {
    width: 30;
    color: #ff4f18;
}

.mcp-server-desc {
    width: 1fr;
    color: #666666;
    padding-left: 1;
}

.mcp-config-btn {
    width: auto;
    min-width: 11;
    height: 1;
    background: #1a1a1a;
    color: #0088ff;
    border: none;
    margin-right: 1;
}

.mcp-config-btn:hover {
    background: #0088ff;
    color: #ffffff;
}

.mcp-toggle-btn {
    width: auto;
    min-width: 9;
    height: 1;
    background: #1a1a1a;
    border: none;
}

.mcp-toggle-btn.-enabled {
    color: #ff3333;
}

.mcp-toggle-btn.-enabled:hover {
    background: #ff3333;
    color: #ffffff;
}

.mcp-toggle-btn.-disabled {
    color: #00cc00;
}

.mcp-toggle-btn.-disabled:hover {
    background: #00cc00;
    color: #000000;
}

.mcp-empty {
    color: #666666;
    text-style: italic;
}

/* Unconfigured MCP servers - not yet added */
.mcp-server-name.-unconfigured {
    color: #666666;
}

.mcp-server-row.-unconfigured {
    opacity: 0.8;
}

.mcp-add-btn {
    width: auto;
    min-width: 5;
    height: 1;
    background: #1a1a1a;
    color: #00cc00;
    border: none;
}

.mcp-add-btn:hover {
    background: #00cc00;
    color: #000000;
}

#mcp-servers-title, #mcp-add-title {
    color: #ffffff;
    text-style: bold;
    margin-top: 1;
}

/* Shared Add/Install section styling */
.settings-instruction {
    color: #666666;
    text-style: italic;
    margin: 1 0;
}

.settings-add-btn {
    width: auto;
    min-width: 10;
    height: 1;
    background: #1a1a1a;
    color: #00cc00;
    border: none;
    margin-top: 1;
}

.settings-add-btn:hover {
    background: #00cc00;
    color: #000000;
}

#mcp-add-input, #skill-install-input {
    width: 100%;
    border: solid #2a2a2a;
    background: #0a0a0a;
    color: #e5e5e5;
    margin-bottom: 1;
}

#mcp-add-input:focus, #skill-install-input:focus {
    border: solid #ff4f18;
}

#mcp-add-actions, #skill-install-actions {
    height: auto;
}

#mcp-hint {
    color: #666666;
    text-style: italic;
    margin-top: 1;
}

/* MCP Environment Editor Modal - positioned as overlay */
#mcp-env-editor {
    width: 60;
    max-width: 90%;
    border: solid #ff4f18;
    background: #0a0a0a;
    padding: 2 3;
}

#mcp-env-title {
    color: #ffffff;
    text-style: bold;
    margin-bottom: 1;
}

#mcp-env-fields {
    height: auto;
    margin: 1 0;
}

.mcp-env-label {
    color: #ff4f18;
    margin-top: 1;
}

.mcp-env-input {
    width: 100%;
    border: solid #2a2a2a;
    background: #000000;
    color: #e5e5e5;
}

.mcp-env-input:focus {
    border: solid #ff4f18;
}

#mcp-env-actions {
    height: auto;
    margin-top: 1;
}

.mcp-env-btn {
    width: auto;
    min-width: 10;
    height: 3;
    background: #333333;
    color: #a0a0a0;
    border: solid #2a2a2a;
    margin-right: 1;
}

.mcp-env-btn:hover {
    background: #ff4f18;
    color: #ffffff;
}

/* Overlay layer for modals */
#mcp-env-overlay, #skill-detail-overlay, #integ-connect-overlay, #integ-detail-overlay, #oauth-waiting-overlay {
    layer: overlay;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.8);
    align: center middle;
}

/* OAuth Waiting Modal */
#oauth-waiting-modal {
    width: 50;
    max-width: 90%;
    border: solid #ff4f18;
    background: #0a0a0a;
    padding: 2 3;
}

#oauth-waiting-title {
    color: #ffffff;
    text-style: bold;
    margin-bottom: 1;
}

.oauth-waiting-desc {
    color: #a0a0a0;
    margin-bottom: 1;
}

.oauth-waiting-hint {
    color: #666666;
    text-style: italic;
    margin-bottom: 1;
}

#oauth-waiting-actions {
    height: auto;
    margin-top: 1;
}

.oauth-waiting-btn {
    width: auto;
    min-width: 10;
    height: 3;
    background: #333333;
    color: #ff4f18;
    border: solid #2a2a2a;
}

.oauth-waiting-btn:hover {
    background: #ff4f18;
    color: #ffffff;
}

/* Skills section - standardized with integration style */
#skills-list {
    height: auto;
    max-height: 15;
    margin: 1 0;
    border: solid #2a2a2a;
    background: #0a0a0a;
    padding: 1;
}

.skill-row {
    height: 1;
    margin-bottom: 1;
}

.skill-name {
    width: 28;
    color: #ff4f18;
}

.skill-desc {
    width: 1fr;
    color: #666666;
    padding-left: 1;
}

.skill-view-btn {
    width: auto;
    min-width: 6;
    height: 1;
    background: #1a1a1a;
    color: #0088ff;
    border: none;
    margin-right: 1;
}

.skill-view-btn:hover {
    background: #0088ff;
    color: #ffffff;
}

.skill-toggle-btn {
    width: auto;
    min-width: 9;
    height: 1;
    background: #1a1a1a;
    border: none;
}

.skill-toggle-btn.-enabled {
    color: #ff3333;
}

.skill-toggle-btn.-enabled:hover {
    background: #ff3333;
    color: #ffffff;
}

.skill-toggle-btn.-disabled {
    color: #00cc00;
}

.skill-toggle-btn.-disabled:hover {
    background: #00cc00;
    color: #000000;
}

.skill-empty {
    color: #666666;
    text-style: italic;
}

#skills-title, #skill-install-title {
    color: #ffffff;
    text-style: bold;
    margin-top: 1;
}

#skills-hint {
    color: #666666;
    text-style: italic;
    margin-top: 1;
}

/* Skill Detail Viewer */
#skill-detail-viewer {
    width: 80;
    max-width: 95%;
    height: auto;
    max-height: 85%;
    border: solid #ff4f18;
    background: #0a0a0a;
    padding: 2 3;
    layout: vertical;
}

#skill-detail-header {
    height: auto;
}

#skill-detail-title-row {
    height: 1;
    margin-bottom: 1;
}

#skill-detail-title {
    color: #ff4f18;
    text-style: bold;
    width: 1fr;
}

#skill-detail-status-btn {
    width: auto;
    min-width: 12;
    height: 1;
    background: #1a1a1a;
    border: none;
}

#skill-detail-status-btn.-enabled {
    color: #00cc00;
}

#skill-detail-status-btn.-disabled {
    color: #ff4f18;
}

#skill-detail-desc {
    color: #a0a0a0;
    margin-bottom: 1;
}

#skill-detail-action-sets {
    color: #666666;
    margin-bottom: 1;
}

#skill-detail-content {
    height: 1fr;
    min-height: 10;
    max-height: 25;
    margin: 1 0;
    border: solid #2a2a2a;
    background: #000000;
    padding: 1;
    overflow-y: auto;
}

#skill-detail-content Static {
    color: #e5e5e5;
}

#skill-detail-actions {
    height: auto;
    margin-top: 1;
    dock: bottom;
}

.skill-detail-btn {
    width: auto;
    min-width: 8;
    height: 1;
    background: #333333;
    color: #a0a0a0;
    border: none;
    margin-right: 1;
}

.skill-detail-btn:hover {
    background: #ff4f18;
    color: #ffffff;
}

.skill-detail-btn.-copy {
    color: #0088ff;
}

.skill-detail-btn.-copy:hover {
    background: #0088ff;
    color: #ffffff;
}

/* =========================================================================
   Integrations Section
   ========================================================================= */

#integrations-list {
    height: auto;
    max-height: 18;
    margin: 1 0;
    border: solid #2a2a2a;
    background: #0a0a0a;
    padding: 1;
}

.integration-row {
    height: 1;
    margin-bottom: 1;
}

.integration-name {
    width: 28;
    color: #ff4f18;
}

.integration-desc {
    width: 1fr;
    color: #666666;
    padding-left: 1;
}

.integration-connect-btn {
    width: auto;
    min-width: 10;
    height: 1;
    background: #1a1a1a;
    color: #00cc00;
    border: none;
}

.integration-connect-btn:hover {
    background: #00cc00;
    color: #000000;
}

.integration-view-btn {
    width: auto;
    min-width: 6;
    height: 1;
    background: #1a1a1a;
    color: #0088ff;
    border: none;
    margin-right: 1;
}

.integration-view-btn:hover {
    background: #0088ff;
    color: #ffffff;
}

.integration-disconnect-btn {
    width: 3;
    min-width: 3;
    height: 1;
    background: #333333;
    color: #ff3333;
    border: none;
}

.integration-disconnect-btn:hover {
    background: #ff3333;
    color: #ffffff;
}

.integration-empty {
    color: #666666;
    text-style: italic;
}

#integrations-title {
    color: #ffffff;
    text-style: bold;
    margin-top: 1;
}

#integrations-hint {
    color: #666666;
    text-style: italic;
    margin-top: 1;
}

/* Integration Connect Modal */
#integ-connect-modal {
    width: 60;
    max-width: 90%;
    border: solid #ff4f18;
    background: #0a0a0a;
    padding: 1 2;
}

#integ-modal-title {
    color: #ffffff;
    text-style: bold;
    margin-bottom: 1;
}

.integ-modal-desc {
    color: #a0a0a0;
    margin-bottom: 1;
}

.integ-modal-hint {
    color: #666666;
    text-style: italic;
}

#integ-modal-fields {
    max-height: 16;
    height: auto;
    margin: 0;
}

.integ-modal-separator {
    color: #606060;
    text-align: center;
    margin-top: 1;
    margin-bottom: 0;
}

.integ-field-label {
    color: #ff4f18;
    margin-top: 0;
}

.integ-field-input {
    width: 100%;
    border: solid #2a2a2a;
    background: #000000;
    color: #e5e5e5;
}

.integ-field-input:focus {
    border: solid #ff4f18;
}

#integ-modal-actions {
    height: auto;
    margin-top: 1;
}

.integ-modal-btn {
    width: auto;
    min-width: 10;
    height: 3;
    background: #333333;
    color: #a0a0a0;
    border: solid #2a2a2a;
    margin-right: 1;
}

.integ-modal-btn:hover {
    background: #ff4f18;
    color: #ffffff;
}

.integ-modal-btn.-primary {
    background: #00cc00;
    color: #000000;
}

.integ-modal-btn.-primary:hover {
    background: #00ff00;
}

/* Integration Detail Viewer */
#integ-detail-viewer {
    width: 70;
    max-width: 95%;
    height: auto;
    max-height: 80%;
    border: solid #ff4f18;
    background: #0a0a0a;
    padding: 2 3;
    layout: vertical;
}

#integ-detail-title {
    color: #ff4f18;
    text-style: bold;
    margin-bottom: 1;
}

#integ-detail-desc {
    color: #a0a0a0;
    margin-bottom: 1;
}

#integ-detail-accounts {
    height: auto;
    min-height: 3;
    max-height: 15;
    margin: 1 0;
    border: solid #2a2a2a;
    background: #000000;
    padding: 1;
}

.integ-account-row {
    height: 1;
    margin-bottom: 1;
}

.integ-account-info {
    width: 1fr;
    color: #e5e5e5;
}

.integ-account-disconnect-btn {
    width: 3;
    min-width: 3;
    height: 1;
    background: #333333;
    color: #ff3333;
    border: none;
}

.integ-account-disconnect-btn:hover {
    background: #ff3333;
    color: #ffffff;
}

.integ-account-empty {
    color: #666666;
    text-style: italic;
}

#integ-detail-actions {
    height: auto;
    margin-top: 1;
}

.integ-detail-btn {
    width: auto;
    min-width: 10;
    height: 1;
    background: #333333;
    color: #a0a0a0;
    border: none;
    margin-right: 1;
}

.integ-detail-btn:hover {
    background: #ff4f18;
    color: #ffffff;
}
"""
