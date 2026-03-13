const axios = require('axios');
const fs = require('fs');
const path = require('path');
const FormData = require('form-data');
const crypto = require('crypto');
const { Pixiv } = require('@ibaraki-douji/pixivts');

const CONFIG_PATH = path.join(__dirname, '../config.json');
const SALT = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c";

function loadConfig() {
  if (fs.existsSync(CONFIG_PATH)) {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  }
  return {};
}

/**
 * Generates X-Client-Time and X-Client-Hash based on reverse engineered APK logic.
 */
function generateXClientHeaders() {
  const time = new Date().toISOString().replace(/\.\d{3}/, ''); // Pixiv style ISO string without ms
  const hash = crypto.createHash('md5').update(time + SALT).digest('hex');
  return {
    'X-Client-Time': time,
    'X-Client-Hash': hash
  };
}

async function getAccessToken() {
  const config = loadConfig();
  const token = config.refresh_token;
  if (!token) throw new Error('No refresh token found. Login first.');

  const pixiv = new Pixiv();
  await pixiv.login(token);
  return pixiv.accessToken;
}

/**
 * Publish an illustration using the AppAPI v2 endpoint.
 * This bypasses the browser and uses pure code.
 */
async function publishAppAPI(filepath, options = {}) {
  const accessToken = await getAccessToken();
  const clientHeaders = generateXClientHeaders();
  
  const form = new FormData();
  form.append('title', options.title || 'Untitled');
  form.append('caption', options.caption || '');
  form.append('type', 'illust');
  form.append('visibility_scope', 'public');
  form.append('x_restrict', String(options.xRestrict || 0));
  form.append('illust_ai_type', String(options.aiType || 2)); // Default to AI generated
  form.append('is_sexual', options.xRestrict > 0 ? 'true' : 'false');
  form.append('is_allow_citation_work', 'true');
  
  if (options.tags && Array.isArray(options.tags)) {
    options.tags.forEach(tag => form.append('tags[]', tag));
  }

  // Pixiv AppAPI uses 'files[]' for the binary data
  form.append('files[]', fs.createReadStream(filepath), {
    filename: path.basename(filepath),
    contentType: 'image/png' // or detection
  });

  console.log(`[AppAPI] Publishing "${options.title}" to Pixiv...`);
  
  try {
    const response = await axios.post('https://app-api.pixiv.net/v2/upload/illust', form, {
      headers: {
        ...form.getHeaders(),
        ...clientHeaders,
        'Authorization': `Bearer ${accessToken}`,
        'User-Agent': 'PixivAndroidApp/6.170.1 (Android 14; Pixel 7)',
        'Accept-Language': 'zh-TW',
        'App-OS': 'android',
        'App-OS-Version': '14',
        'App-Version': '6.170.1'
      }
    });
    return response.data;
  } catch (error) {
    if (error.response && error.response.data) {
      throw new Error(`Pixiv API Error: ${JSON.stringify(error.response.data)}`);
    }
    throw error;
  }
}

// CLI Handling
async function main() {
  const args = process.argv.slice(2);
  const filepath = args[0];
  const title = args[1] || "AI Test Upload";
  const tags = args[2] ? args[2].split(',') : ['AI生成', 'ComfyUI', 'Arch'];

  if (!filepath || !fs.existsSync(filepath)) {
    console.log("Usage: node pixiv-app-publish.js <image_path> [title] [tags_comma_separated]");
    process.exit(1);
  }

  try {
    const result = await publishAppAPI(filepath, {
      title,
      tags
    });
    console.log("Successfully published via AppAPI!");
    console.log(JSON.stringify(result, null, 2));
  } catch (e) {
    console.error("Failed:", e.message);
  }
}

if (require.main === module) {
  main();
}
