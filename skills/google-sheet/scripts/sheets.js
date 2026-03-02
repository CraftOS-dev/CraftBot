#!/usr/bin/env node
/**
 * Google Sheets CLI Tool
 * Usage: node sheets.js <command> [options]
 * 
 * Commands:
 *   read <spreadsheetId> <range>              Read data from a range
 *   write <spreadsheetId> <range> <data>      Write data to a range (JSON array)
 *   append <spreadsheetId> <range> <data>     Append rows to a sheet (JSON array)
 *   clear <spreadsheetId> <range>             Clear a range
 *   create <title>                            Create a new spreadsheet
 *   info <spreadsheetId>                      Get spreadsheet metadata
 *   format <spreadsheetId> <range> <formatJson>  Format cells (bg color, text, borders)
 *   merge <spreadsheetId> <range>             Merge cells in range
 *   unmerge <spreadsheetId> <range>           Unmerge cells in range
 * 
 * Environment:
 *   GOOGLE_SERVICE_ACCOUNT_KEY   Path to service account JSON key file
 *   GOOGLE_SHEETS_KEY_FILE       Alternative env var for key file path
 */

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');

// Find credentials
function getCredentialsPath() {
  const envPath = process.env.GOOGLE_SERVICE_ACCOUNT_KEY || 
                  process.env.GOOGLE_SHEETS_KEY_FILE;
  
  if (envPath && fs.existsSync(envPath)) {
    return envPath;
  }
  
  // Check common locations
  const locations = [
    path.join(process.cwd(), 'service-account.json'),
    path.join(process.cwd(), 'credentials.json'),
    path.join(process.env.HOME || '', '.config/google-sheets/credentials.json'),
  ];
  
  for (const loc of locations) {
    if (fs.existsSync(loc)) {
      return loc;
    }
  }
  
  return null;
}

async function getAuthClient() {
  const credPath = getCredentialsPath();
  
  if (!credPath) {
    console.error('Error: No credentials found.');
    console.error('Set GOOGLE_SERVICE_ACCOUNT_KEY env var or place credentials.json in cwd.');
    process.exit(1);
  }
  
  const credentials = JSON.parse(fs.readFileSync(credPath, 'utf8'));
  
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ['https://www.googleapis.com/auth/spreadsheets'],
  });
  
  return auth;
}

async function getSheetsClient() {
  const auth = await getAuthClient();
  return google.sheets({ version: 'v4', auth });
}

// Commands
async function readRange(spreadsheetId, range) {
  const sheets = await getSheetsClient();
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range,
  });
  return response.data.values || [];
}

async function writeRange(spreadsheetId, range, values) {
  const sheets = await getSheetsClient();
  const response = await sheets.spreadsheets.values.update({
    spreadsheetId,
    range,
    valueInputOption: 'USER_ENTERED',
    requestBody: { values },
  });
  return {
    updatedCells: response.data.updatedCells,
    updatedRange: response.data.updatedRange,
  };
}

async function appendRows(spreadsheetId, range, values) {
  const sheets = await getSheetsClient();
  const response = await sheets.spreadsheets.values.append({
    spreadsheetId,
    range,
    valueInputOption: 'USER_ENTERED',
    insertDataOption: 'INSERT_ROWS',
    requestBody: { values },
  });
  return {
    updatedCells: response.data.updates?.updatedCells,
    updatedRange: response.data.updates?.updatedRange,
  };
}

async function clearRange(spreadsheetId, range) {
  const sheets = await getSheetsClient();
  const response = await sheets.spreadsheets.values.clear({
    spreadsheetId,
    range,
  });
  return { clearedRange: response.data.clearedRange };
}

async function createSpreadsheet(title) {
  const sheets = await getSheetsClient();
  const response = await sheets.spreadsheets.create({
    requestBody: {
      properties: { title },
    },
  });
  return {
    spreadsheetId: response.data.spreadsheetId,
    spreadsheetUrl: response.data.spreadsheetUrl,
  };
}

async function getSpreadsheetInfo(spreadsheetId) {
  const sheets = await getSheetsClient();
  const response = await sheets.spreadsheets.get({
    spreadsheetId,
  });
  
  const { properties, sheets: sheetList } = response.data;
  return {
    title: properties.title,
    locale: properties.locale,
    timeZone: properties.timeZone,
    sheets: sheetList.map(s => ({
      sheetId: s.properties.sheetId,
      title: s.properties.title,
      rowCount: s.properties.gridProperties?.rowCount,
      columnCount: s.properties.gridProperties?.columnCount,
    })),
  };
}

// Helper: Parse A1 notation to grid range
function parseA1Notation(range, sheetId = 0) {
  // Extract sheet name if present
  let sheetName = null;
  let cellRange = range;
  
  if (range.includes('!')) {
    const parts = range.split('!');
    sheetName = parts[0].replace(/'/g, '');
    cellRange = parts[1];
  }
  
  // Parse cell range (e.g., "A1:C5" or "A1")
  const match = cellRange.match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/i);
  if (!match) {
    throw new Error(`Invalid range format: ${cellRange}`);
  }
  
  const colToIndex = (col) => {
    let index = 0;
    for (let i = 0; i < col.length; i++) {
      index = index * 26 + (col.charCodeAt(i) - 'A'.charCodeAt(0) + 1);
    }
    return index - 1;
  };
  
  const startCol = colToIndex(match[1].toUpperCase());
  const startRow = parseInt(match[2]) - 1;
  const endCol = match[3] ? colToIndex(match[3].toUpperCase()) + 1 : startCol + 1;
  const endRow = match[4] ? parseInt(match[4]) : startRow + 1;
  
  return {
    sheetId,
    sheetName,
    startRowIndex: startRow,
    endRowIndex: endRow,
    startColumnIndex: startCol,
    endColumnIndex: endCol,
  };
}

// Helper: Get sheet ID by name
async function getSheetIdByName(spreadsheetId, sheetName) {
  const info = await getSpreadsheetInfo(spreadsheetId);
  const sheet = info.sheets.find(s => s.title === sheetName);
  if (!sheet) {
    throw new Error(`Sheet "${sheetName}" not found`);
  }
  return sheet.sheetId;
}

// Format cells
async function formatCells(spreadsheetId, range, formatOptions) {
  const sheets = await getSheetsClient();
  
  // Parse range
  const gridRange = parseA1Notation(range);
  
  // Get sheetId if sheet name was provided
  if (gridRange.sheetName) {
    gridRange.sheetId = await getSheetIdByName(spreadsheetId, gridRange.sheetName);
  }
  
  // Build cell format
  const cellFormat = {};
  const fields = [];
  
  // Background color
  if (formatOptions.backgroundColor) {
    const bg = formatOptions.backgroundColor;
    cellFormat.backgroundColor = {
      red: (bg.red || 0) / 255,
      green: (bg.green || 0) / 255,
      blue: (bg.blue || 0) / 255,
    };
    fields.push('userEnteredFormat.backgroundColor');
  }
  
  // Text format
  if (formatOptions.textFormat) {
    cellFormat.textFormat = {};
    const tf = formatOptions.textFormat;
    
    if (tf.bold !== undefined) {
      cellFormat.textFormat.bold = tf.bold;
      fields.push('userEnteredFormat.textFormat.bold');
    }
    if (tf.italic !== undefined) {
      cellFormat.textFormat.italic = tf.italic;
      fields.push('userEnteredFormat.textFormat.italic');
    }
    if (tf.fontSize !== undefined) {
      cellFormat.textFormat.fontSize = tf.fontSize;
      fields.push('userEnteredFormat.textFormat.fontSize');
    }
    if (tf.foregroundColor) {
      cellFormat.textFormat.foregroundColor = {
        red: (tf.foregroundColor.red || 0) / 255,
        green: (tf.foregroundColor.green || 0) / 255,
        blue: (tf.foregroundColor.blue || 0) / 255,
      };
      fields.push('userEnteredFormat.textFormat.foregroundColor');
    }
  }
  
  // Horizontal alignment
  if (formatOptions.horizontalAlignment) {
    cellFormat.horizontalAlignment = formatOptions.horizontalAlignment.toUpperCase();
    fields.push('userEnteredFormat.horizontalAlignment');
  }
  
  // Vertical alignment
  if (formatOptions.verticalAlignment) {
    cellFormat.verticalAlignment = formatOptions.verticalAlignment.toUpperCase();
    fields.push('userEnteredFormat.verticalAlignment');
  }
  
  // Wrap strategy
  if (formatOptions.wrapStrategy) {
    cellFormat.wrapStrategy = formatOptions.wrapStrategy.toUpperCase();
    fields.push('userEnteredFormat.wrapStrategy');
  }
  
  const requests = [{
    repeatCell: {
      range: {
        sheetId: gridRange.sheetId,
        startRowIndex: gridRange.startRowIndex,
        endRowIndex: gridRange.endRowIndex,
        startColumnIndex: gridRange.startColumnIndex,
        endColumnIndex: gridRange.endColumnIndex,
      },
      cell: {
        userEnteredFormat: cellFormat,
      },
      fields: fields.join(','),
    },
  }];
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: { requests },
  });
  
  return { 
    updatedCells: (gridRange.endRowIndex - gridRange.startRowIndex) * 
                  (gridRange.endColumnIndex - gridRange.startColumnIndex),
    replies: response.data.replies,
  };
}

// Merge cells
async function mergeCells(spreadsheetId, range, mergeType = 'MERGE_ALL') {
  const sheets = await getSheetsClient();
  const gridRange = parseA1Notation(range);
  
  if (gridRange.sheetName) {
    gridRange.sheetId = await getSheetIdByName(spreadsheetId, gridRange.sheetName);
  }
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        mergeCells: {
          range: {
            sheetId: gridRange.sheetId,
            startRowIndex: gridRange.startRowIndex,
            endRowIndex: gridRange.endRowIndex,
            startColumnIndex: gridRange.startColumnIndex,
            endColumnIndex: gridRange.endColumnIndex,
          },
          mergeType,
        },
      }],
    },
  });
  
  return { merged: true, range };
}

// Unmerge cells
async function unmergeCells(spreadsheetId, range) {
  const sheets = await getSheetsClient();
  const gridRange = parseA1Notation(range);
  
  if (gridRange.sheetName) {
    gridRange.sheetId = await getSheetIdByName(spreadsheetId, gridRange.sheetName);
  }
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        unmergeCells: {
          range: {
            sheetId: gridRange.sheetId,
            startRowIndex: gridRange.startRowIndex,
            endRowIndex: gridRange.endRowIndex,
            startColumnIndex: gridRange.startColumnIndex,
            endColumnIndex: gridRange.endColumnIndex,
          },
        },
      }],
    },
  });
  
  return { unmerged: true, range };
}

// CLI
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];
  
  if (!command) {
    console.error('Usage: node sheets.js <command> [options]');
    console.error('Commands: read, write, append, clear, create, info, format, merge, unmerge');
    process.exit(1);
  }
  
  try {
    let result;
    
    switch (command) {
      case 'read': {
        const [, spreadsheetId, range] = args;
        if (!spreadsheetId || !range) {
          console.error('Usage: node sheets.js read <spreadsheetId> <range>');
          process.exit(1);
        }
        result = await readRange(spreadsheetId, range);
        break;
      }
      
      case 'write': {
        const [, spreadsheetId, range, dataJson] = args;
        if (!spreadsheetId || !range || !dataJson) {
          console.error('Usage: node sheets.js write <spreadsheetId> <range> <jsonData>');
          console.error('Example: node sheets.js write ABC123 "Sheet1!A1:B2" \'[["a","b"],["c","d"]]\'');
          process.exit(1);
        }
        const data = JSON.parse(dataJson);
        result = await writeRange(spreadsheetId, range, data);
        break;
      }
      
      case 'append': {
        const [, spreadsheetId, range, dataJson] = args;
        if (!spreadsheetId || !range || !dataJson) {
          console.error('Usage: node sheets.js append <spreadsheetId> <range> <jsonData>');
          console.error('Example: node sheets.js append ABC123 "Sheet1!A:B" \'[["newRow1","newRow2"]]\'');
          process.exit(1);
        }
        const data = JSON.parse(dataJson);
        result = await appendRows(spreadsheetId, range, data);
        break;
      }
      
      case 'clear': {
        const [, spreadsheetId, range] = args;
        if (!spreadsheetId || !range) {
          console.error('Usage: node sheets.js clear <spreadsheetId> <range>');
          process.exit(1);
        }
        result = await clearRange(spreadsheetId, range);
        break;
      }
      
      case 'create': {
        const [, title] = args;
        if (!title) {
          console.error('Usage: node sheets.js create <title>');
          process.exit(1);
        }
        result = await createSpreadsheet(title);
        break;
      }
      
      case 'info': {
        const [, spreadsheetId] = args;
        if (!spreadsheetId) {
          console.error('Usage: node sheets.js info <spreadsheetId>');
          process.exit(1);
        }
        result = await getSpreadsheetInfo(spreadsheetId);
        break;
      }
      
      case 'format': {
        const [, spreadsheetId, range, formatJson] = args;
        if (!spreadsheetId || !range || !formatJson) {
          console.error('Usage: node sheets.js format <spreadsheetId> <range> <formatJson>');
          console.error('Format options: backgroundColor, textFormat, horizontalAlignment, verticalAlignment, wrapStrategy');
          console.error('Example: node sheets.js format ABC123 "Sheet1!A1:B2" \'{"backgroundColor":{"red":255,"green":255,"blue":0},"textFormat":{"bold":true}}\'');
          process.exit(1);
        }
        const formatOptions = JSON.parse(formatJson);
        result = await formatCells(spreadsheetId, range, formatOptions);
        break;
      }
      
      case 'merge': {
        const [, spreadsheetId, range] = args;
        if (!spreadsheetId || !range) {
          console.error('Usage: node sheets.js merge <spreadsheetId> <range>');
          process.exit(1);
        }
        result = await mergeCells(spreadsheetId, range);
        break;
      }
      
      case 'unmerge': {
        const [, spreadsheetId, range] = args;
        if (!spreadsheetId || !range) {
          console.error('Usage: node sheets.js unmerge <spreadsheetId> <range>');
          process.exit(1);
        }
        result = await unmergeCells(spreadsheetId, range);
        break;
      }
      
      case 'getFormat': {
        const [, spreadsheetId, range] = args;
        if (!spreadsheetId || !range) {
          console.error('Usage: node sheets.js getFormat <spreadsheetId> <range>');
          process.exit(1);
        }
        result = await getCellFormats(spreadsheetId, range);
        break;
      }
      
      case 'borders': {
        const [, spreadsheetId, range, styleJson] = args;
        if (!spreadsheetId || !range) {
          console.error('Usage: node sheets.js borders <spreadsheetId> <range> [styleJson]');
          console.error('Example: node sheets.js borders ABC123 "Sheet1!A1:C3" \'{"style":"SOLID","color":{"red":0,"green":0,"blue":0}}\'');
          process.exit(1);
        }
        const style = styleJson ? JSON.parse(styleJson) : undefined;
        result = await addBorders(spreadsheetId, range, style);
        break;
      }
      
      case 'resize': {
        const [, spreadsheetId, sheetName, dimension, start, end, size] = args;
        if (!spreadsheetId || !sheetName || !dimension || !start || !end || !size) {
          console.error('Usage: node sheets.js resize <spreadsheetId> <sheetName> <cols|rows> <start> <end> <pixelSize>');
          console.error('Example: node sheets.js resize ABC123 "Sheet1" cols A C 150');
          process.exit(1);
        }
        if (dimension === 'cols') {
          result = await resizeColumns(spreadsheetId, sheetName, start, end, parseInt(size));
        } else {
          result = await resizeRows(spreadsheetId, sheetName, parseInt(start), parseInt(end), parseInt(size));
        }
        break;
      }
      
      case 'freeze': {
        const [, spreadsheetId, sheetName, rows, cols] = args;
        if (!spreadsheetId || !sheetName) {
          console.error('Usage: node sheets.js freeze <spreadsheetId> <sheetName> [rows] [cols]');
          console.error('Example: node sheets.js freeze ABC123 "Sheet1" 1 1');
          process.exit(1);
        }
        result = await freeze(spreadsheetId, sheetName, rows ? parseInt(rows) : undefined, cols ? parseInt(cols) : undefined);
        break;
      }
      
      case 'addSheet': {
        const [, spreadsheetId, title] = args;
        if (!spreadsheetId || !title) {
          console.error('Usage: node sheets.js addSheet <spreadsheetId> <title>');
          process.exit(1);
        }
        result = await addSheet(spreadsheetId, title);
        break;
      }
      
      case 'deleteSheet': {
        const [, spreadsheetId, sheetName] = args;
        if (!spreadsheetId || !sheetName) {
          console.error('Usage: node sheets.js deleteSheet <spreadsheetId> <sheetName>');
          process.exit(1);
        }
        result = await deleteSheet(spreadsheetId, sheetName);
        break;
      }
      
      case 'renameSheet': {
        const [, spreadsheetId, oldName, newName] = args;
        if (!spreadsheetId || !oldName || !newName) {
          console.error('Usage: node sheets.js renameSheet <spreadsheetId> <oldName> <newName>');
          process.exit(1);
        }
        result = await renameSheet(spreadsheetId, oldName, newName);
        break;
      }
      
      case 'autoResize': {
        const [, spreadsheetId, sheetName, startCol, endCol] = args;
        if (!spreadsheetId || !sheetName || !startCol || !endCol) {
          console.error('Usage: node sheets.js autoResize <spreadsheetId> <sheetName> <startCol> <endCol>');
          console.error('Example: node sheets.js autoResize ABC123 "Sheet1" A Z');
          process.exit(1);
        }
        result = await autoResize(spreadsheetId, sheetName, startCol, endCol);
        break;
      }
      
      case 'copyFormat': {
        const [, spreadsheetId, sourceRange, destRange] = args;
        if (!spreadsheetId || !sourceRange || !destRange) {
          console.error('Usage: node sheets.js copyFormat <spreadsheetId> <sourceRange> <destRange>');
          console.error('Example: node sheets.js copyFormat ABC123 "Sheet1!A1:C3" "Sheet1!D1:F3"');
          process.exit(1);
        }
        result = await copyFormat(spreadsheetId, sourceRange, destRange);
        break;
      }
      
      default:
        console.error(`Unknown command: ${command}`);
        console.error('Commands: read, write, append, clear, create, info, format, merge, unmerge, getFormat, borders, resize, freeze, addSheet, deleteSheet, renameSheet, autoResize, copyFormat');
        process.exit(1);
    }
    
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Error:', error.message);
    if (error.response?.data?.error) {
      console.error('Details:', JSON.stringify(error.response.data.error, null, 2));
    }
    process.exit(1);
  }
}

main();

// Get cell formats
async function getCellFormats(spreadsheetId, range) {
  const sheets = await getSheetsClient();
  const gridRange = parseA1Notation(range);
  
  if (gridRange.sheetName) {
    gridRange.sheetId = await getSheetIdByName(spreadsheetId, gridRange.sheetName);
  }
  
  const response = await sheets.spreadsheets.get({
    spreadsheetId,
    ranges: [range],
    includeGridData: true,
  });
  
  const sheetData = response.data.sheets[0]?.data[0];
  if (!sheetData) return [];
  
  const formats = [];
  for (const row of sheetData.rowData || []) {
    const rowFormats = [];
    for (const cell of row.values || []) {
      const fmt = cell.effectiveFormat || {};
      rowFormats.push({
        backgroundColor: fmt.backgroundColor,
        textFormat: fmt.textFormat,
        horizontalAlignment: fmt.horizontalAlignment,
        verticalAlignment: fmt.verticalAlignment,
        wrapStrategy: fmt.wrapStrategy,
        borders: fmt.borders,
      });
    }
    formats.push(rowFormats);
  }
  return formats;
}

// Add borders
async function addBorders(spreadsheetId, range, borderStyle) {
  const sheets = await getSheetsClient();
  const gridRange = parseA1Notation(range);
  
  if (gridRange.sheetName) {
    gridRange.sheetId = await getSheetIdByName(spreadsheetId, gridRange.sheetName);
  }
  
  const style = borderStyle || { style: 'SOLID', color: { red: 0, green: 0, blue: 0 } };
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        updateBorders: {
          range: {
            sheetId: gridRange.sheetId,
            startRowIndex: gridRange.startRowIndex,
            endRowIndex: gridRange.endRowIndex,
            startColumnIndex: gridRange.startColumnIndex,
            endColumnIndex: gridRange.endColumnIndex,
          },
          top: style,
          bottom: style,
          left: style,
          right: style,
          innerHorizontal: style,
          innerVertical: style,
        },
      }],
    },
  });
  
  return { bordersAdded: true, range };
}

// Resize columns
async function resizeColumns(spreadsheetId, sheetName, startCol, endCol, pixelSize) {
  const sheets = await getSheetsClient();
  const sheetId = await getSheetIdByName(spreadsheetId, sheetName);
  
  const colToIndex = (col) => {
    let index = 0;
    for (let i = 0; i < col.length; i++) {
      index = index * 26 + (col.charCodeAt(i) - 'A'.charCodeAt(0) + 1);
    }
    return index - 1;
  };
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        updateDimensionProperties: {
          range: {
            sheetId,
            dimension: 'COLUMNS',
            startIndex: colToIndex(startCol),
            endIndex: colToIndex(endCol) + 1,
          },
          properties: { pixelSize },
          fields: 'pixelSize',
        },
      }],
    },
  });
  
  return { resized: true, columns: `${startCol}:${endCol}`, pixelSize };
}

// Resize rows
async function resizeRows(spreadsheetId, sheetName, startRow, endRow, pixelSize) {
  const sheets = await getSheetsClient();
  const sheetId = await getSheetIdByName(spreadsheetId, sheetName);
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        updateDimensionProperties: {
          range: {
            sheetId,
            dimension: 'ROWS',
            startIndex: startRow - 1,
            endIndex: endRow,
          },
          properties: { pixelSize },
          fields: 'pixelSize',
        },
      }],
    },
  });
  
  return { resized: true, rows: `${startRow}:${endRow}`, pixelSize };
}

// Freeze rows/columns
async function freeze(spreadsheetId, sheetName, frozenRowCount, frozenColumnCount) {
  const sheets = await getSheetsClient();
  const sheetId = await getSheetIdByName(spreadsheetId, sheetName);
  
  const properties = {};
  const fields = [];
  
  if (frozenRowCount !== undefined) {
    properties.frozenRowCount = frozenRowCount;
    fields.push('frozenRowCount');
  }
  if (frozenColumnCount !== undefined) {
    properties.frozenColumnCount = frozenColumnCount;
    fields.push('frozenColumnCount');
  }
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        updateSheetProperties: {
          properties: {
            sheetId,
            gridProperties: properties,
          },
          fields: `gridProperties(${fields.join(',')})`,
        },
      }],
    },
  });
  
  return { frozen: true, frozenRowCount, frozenColumnCount };
}

// Add new sheet
async function addSheet(spreadsheetId, title) {
  const sheets = await getSheetsClient();
  
  const response = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        addSheet: {
          properties: { title },
        },
      }],
    },
  });
  
  const newSheet = response.data.replies[0].addSheet.properties;
  return { sheetId: newSheet.sheetId, title: newSheet.title };
}

// Delete sheet
async function deleteSheet(spreadsheetId, sheetName) {
  const sheets = await getSheetsClient();
  const sheetId = await getSheetIdByName(spreadsheetId, sheetName);
  
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        deleteSheet: { sheetId },
      }],
    },
  });
  
  return { deleted: true, sheetName };
}

// Rename sheet
async function renameSheet(spreadsheetId, oldName, newName) {
  const sheets = await getSheetsClient();
  const sheetId = await getSheetIdByName(spreadsheetId, oldName);
  
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        updateSheetProperties: {
          properties: {
            sheetId,
            title: newName,
          },
          fields: 'title',
        },
      }],
    },
  });
  
  return { renamed: true, oldName, newName };
}

// Auto resize columns to fit content
async function autoResize(spreadsheetId, sheetName, startCol, endCol) {
  const sheets = await getSheetsClient();
  const sheetId = await getSheetIdByName(spreadsheetId, sheetName);
  
  const colToIndex = (col) => {
    let index = 0;
    for (let i = 0; i < col.length; i++) {
      index = index * 26 + (col.charCodeAt(i) - 'A'.charCodeAt(0) + 1);
    }
    return index - 1;
  };
  
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        autoResizeDimensions: {
          dimensions: {
            sheetId,
            dimension: 'COLUMNS',
            startIndex: colToIndex(startCol),
            endIndex: colToIndex(endCol) + 1,
          },
        },
      }],
    },
  });
  
  return { autoResized: true, columns: `${startCol}:${endCol}` };
}

// Copy format from one range to another
async function copyFormat(spreadsheetId, sourceRange, destRange) {
  const sheets = await getSheetsClient();
  const sourceGrid = parseA1Notation(sourceRange);
  const destGrid = parseA1Notation(destRange);
  
  if (sourceGrid.sheetName) {
    sourceGrid.sheetId = await getSheetIdByName(spreadsheetId, sourceGrid.sheetName);
  }
  if (destGrid.sheetName) {
    destGrid.sheetId = await getSheetIdByName(spreadsheetId, destGrid.sheetName);
  }
  
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{
        copyPaste: {
          source: {
            sheetId: sourceGrid.sheetId,
            startRowIndex: sourceGrid.startRowIndex,
            endRowIndex: sourceGrid.endRowIndex,
            startColumnIndex: sourceGrid.startColumnIndex,
            endColumnIndex: sourceGrid.endColumnIndex,
          },
          destination: {
            sheetId: destGrid.sheetId,
            startRowIndex: destGrid.startRowIndex,
            endRowIndex: destGrid.endRowIndex,
            startColumnIndex: destGrid.startColumnIndex,
            endColumnIndex: destGrid.endColumnIndex,
          },
          pasteType: 'PASTE_FORMAT',
        },
      }],
    },
  });
  
  return { copiedFormat: true, from: sourceRange, to: destRange };
}
