const { Pixiv, Illusts } = require('@ibaraki-douji/pixivts');
const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');
const GifEncoder = require('gif-encoder-2');
const { PNG } = require('pngjs');
const jpeg = require('jpeg-js');
const axios = require('axios');

const CONFIG_PATH = path.join(__dirname, '../config.json');
const DOWNLOAD_DIR = path.join(__dirname, '../downloads');

if (!fs.existsSync(DOWNLOAD_DIR)) {
  fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });
}

function loadConfig() {
  if (fs.existsSync(CONFIG_PATH)) {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  }
  return {};
}

async function getClient() {
  const config = loadConfig();
  const token = process.env.PIXIV_REFRESH_TOKEN || config.refresh_token;
  if (!token) {
    throw new Error('No refresh token found.');
  }
  const pixiv = new Pixiv();
  await pixiv.login(token);
  return pixiv;
}

async function downloadZip(url, accessToken) {
  const response = await axios({
    method: 'GET',
    url: url,
    responseType: 'arraybuffer',
    headers: {
      'User-Agent': 'PixivAndroidApp/5.0.234 (Android 11; Pixel 5)',
      'Referer': 'https://www.pixiv.net/',
      'Authorization': `Bearer ${accessToken}`
    }
  });
  return response.data;
}

async function decodeImage(buffer, mimeType) {
  if (mimeType === 'image/png') {
    return new Promise((resolve, reject) => {
      new PNG().parse(buffer, (error, data) => {
        if (error) reject(error);
        else resolve(data);
      });
    });
  } else if (mimeType === 'image/jpeg' || mimeType === 'image/jpg') {
    return jpeg.decode(buffer, { useTArray: true }); // Returns { width, height, data }
  } else {
    throw new Error(`Unsupported mime type: ${mimeType}`);
  }
}

async function main() {
  const illustId = process.argv[2];
  if (!illustId) {
    console.error('Usage: node download-ugoira.js <illustId>');
    process.exit(1);
  }

  try {
    const pixiv = await getClient();
    const illusts = new Illusts(pixiv);

    console.log(`Fetching metadata for ${illustId}...`);
    const illust = await illusts.getIllustById(illustId);
    if (illust.type !== 'ugoira') {
      console.error('Error: This illustration is not an ugoira.');
      process.exit(1);
    }

    const metaResponse = await illusts.getUgoiraMetadata(illustId);
    console.log('Meta response keys:', Object.keys(metaResponse));
    const meta = metaResponse.ugoira_metadata || metaResponse; // Try both
    if (!meta || !meta.zip_urls) {
        console.error('Invalid metadata structure:', JSON.stringify(metaResponse, null, 2));
        process.exit(1);
    }
    const zipUrl = meta.zip_urls.medium;
    const frames = meta.frames;

    console.log(`Downloading zip from ${zipUrl}...`);
    const zipData = await downloadZip(zipUrl, pixiv.accessToken);
    
    console.log('Extracting zip...');
    const zip = new AdmZip(zipData);
    const zipEntries = zip.getEntries();
    
    // Create a map of filename -> entry
    const entryMap = {};
    zipEntries.forEach(entry => {
      entryMap[entry.entryName] = entry;
    });

    // Prepare Encoder
    // We need dimensions. Decode first frame to get them.
    const firstFrameEntry = entryMap[frames[0].file];
    const firstFrameBuffer = firstFrameEntry.getData();
    let firstMime = 'image/jpeg'; // Default
    if (frames[0].file.endsWith('.png')) firstMime = 'image/png';
    
    const firstImage = await decodeImage(firstFrameBuffer, firstMime);
    
    const width = firstImage.width;
    const height = firstImage.height;

    console.log(`Encoding GIF (${width}x${height}, ${frames.length} frames)...`);
    
    const encoder = new GifEncoder(width, height);
    encoder.setDelay(frames[0].delay); // Initial delay
    encoder.start();

    for (let i = 0; i < frames.length; i++) {
      const frame = frames[i];
      const entry = entryMap[frame.file];
      const buffer = entry.getData();
      
      // Determine type from file extension
      let mime = 'image/jpeg';
      if (frame.file.endsWith('.png')) mime = 'image/png';

      const image = await decodeImage(buffer, mime);
      
      encoder.setDelay(frame.delay);
      encoder.addFrame(image.data);
      
      if ((i + 1) % 10 === 0) console.log(`Processed ${i + 1}/${frames.length} frames...`);
    }

    encoder.finish();
    const buffer = encoder.out.getData();
    
    const outputPath = path.join(DOWNLOAD_DIR, `${illustId}.gif`);
    fs.writeFileSync(outputPath, buffer);
    
    console.log(`Saved to ${outputPath}`);
    console.log(JSON.stringify({ path: outputPath }));

  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  }
}

main();
