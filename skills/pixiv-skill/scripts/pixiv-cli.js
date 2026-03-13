#!/usr/bin/env node
const { Pixiv, Illusts, Users, Account } = require('@ibaraki-douji/pixivts');
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const FormData = require('form-data');
const crypto = require('crypto');

const CONFIG_PATH = path.join(__dirname, '../config.json');
const DOWNLOAD_DIR = path.join(__dirname, '../downloads');
// Reverse engineered Salt from Pixiv Android APK
const SALT = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c";

if (!fs.existsSync(DOWNLOAD_DIR)) {
  fs.mkdirSync(DOWNLOAD_DIR);
}

function loadConfig() {
  if (fs.existsSync(CONFIG_PATH)) {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  }
  return {};
}

function saveConfig(config) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
}

/**
 * Generates headers required by Pixiv AppAPI.
 * Logic extracted from decompiled lm/e.java
 */
function generateXClientHeaders() {
  const time = new Date().toISOString().replace(/\.\d{3}/, ''); 
  const hash = crypto.createHash('md5').update(time + SALT).digest('hex');
  return {
    'X-Client-Time': time,
    'X-Client-Hash': hash
  };
}

async function getClient() {
  const config = loadConfig();
  const token = process.env.PIXIV_REFRESH_TOKEN || config.refresh_token;

  if (!token) {
    console.error('Error: No refresh token found. Run "node pixiv-cli.js login <token>" first.');
    process.exit(1);
  }

  const pixiv = new Pixiv();
  try {
    await pixiv.login(token);
    return pixiv;
  } catch (error) {
    console.error('Login failed:', error.message);
    process.exit(1);
  }
}

/**
 * Pure-code publishing via AppAPI v2.
 * Logic extracted from cp/a.java and zo/a.java
 */
async function postIllustration(filepath, title, tags, options = {}) {
  const pixiv = await getClient();
  const clientHeaders = generateXClientHeaders();
  
  const visibilityMap = {
    'public': 0,
    'login_only': 1,
    'mypixiv': 3,
    'private': 4
  };
  const visibilityValue = visibilityMap[options.visibility] !== undefined ? visibilityMap[options.visibility] : 0;

  // x_restrict mapping from reverse engineered fv/e.java
  const xRestrictMap = {
    0: 'none',
    1: 'r18',
    2: 'r18g'
  };
  const xRestrictValue = xRestrictMap[options.xRestrict || 0] || 'none';

  const form = new FormData();
  form.append('title', title);
  form.append('caption', options.caption || '');
  form.append('type', 'illust');
  form.append('visibility_scope', visibilityValue);
  form.append('x_restrict', xRestrictValue);
  form.append('illust_ai_type', options.aiType || 2); 
  form.append('is_sexual', options.xRestrict > 0 ? 'true' : 'false');
  form.append('is_allow_citation_work', 'true');
  
  if (tags && Array.isArray(tags)) {
    tags.forEach(tag => form.append('tags[]', tag));
  }

  form.append('files[]', fs.createReadStream(filepath), {
    filename: path.basename(filepath)
  });

  const response = await axios.post('https://app-api.pixiv.net/v2/upload/illust', form, {
    headers: {
      ...form.getHeaders(),
      ...clientHeaders,
      'Authorization': `Bearer ${pixiv.accessToken}`,
      'User-Agent': 'PixivAndroidApp/6.170.1 (Android 14; Pixel 7)',
      'App-OS': 'android',
      'App-OS-Version': '14',
      'App-Version': '6.170.1',
      'Accept-Language': 'zh-TW'
    }
  });

  if (response.data && response.data.convert_key) {
    const key = response.data.convert_key;
    console.log(`[AppAPI] Upload accepted. Convert Key: ${key}. Polling for completion...`);
    
    // Poll for status
    for (let i = 0; i < 10; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const statusHeaders = generateXClientHeaders();
      const statusRes = await axios.post(`https://app-api.pixiv.net/v1/upload/status`, 
        new URLSearchParams({ convert_key: key }).toString(),
        {
          headers: {
            ...statusHeaders,
            'Authorization': `Bearer ${pixiv.accessToken}`,
            'User-Agent': 'PixivAndroidApp/6.170.1 (Android 14; Pixel 7)',
            'Content-Type': 'application/x-www-form-urlencoded'
          }
        }
      );
      
      console.log(`[AppAPI] Status Check ${i+1}: ${statusRes.data.status}`);
      if (statusRes.data.status === 'success' || statusRes.data.status === 'COMPLETE') {
        return { ok: true, message: 'Successfully published!', data: statusRes.data };
      }
      if (statusRes.data.status === 'failure') {
        throw new Error('Pixiv reported upload failure during conversion.');
      }
    }
  }

  return response.data;
}

async function downloadFile(url, filepath, token) {
  const writer = fs.createWriteStream(filepath);
  const response = await axios({
    url,
    method: 'GET',
    responseType: 'stream',
    headers: {
      'Referer': 'https://www.pixiv.net/',
      'User-Agent': 'PixivAndroidApp/5.0.234 (Android 6.0; PixivAndroidApp)'
    }
  });
  response.data.pipe(writer);
  return new Promise((resolve, reject) => {
    writer.on('finish', resolve);
    writer.on('error', reject);
  });
}

async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (command === 'login') {
    const token = args[1];
    if (!token) {
      console.error('Usage: login <refreshToken>');
      process.exit(1);
    }
    const config = loadConfig();
    config.refresh_token = token;
    saveConfig(config);
    console.log('Token saved to config.json');
    return;
  }

  if (command === 'post') {
    const filepath = args[1];
    const title = args[2];
    const tags = (args[3] || '').split(',').map(t => t.trim()).filter(t => t);
    const visibility = args[4] || 'public';
    
    if (!filepath || !title) {
      console.error('Usage: post <filepath> <title> [tags_comma_separated] [visibility]');
      process.exit(1);
    }

    try {
      const result = await postIllustration(filepath, title, tags, { visibility });
      console.log('Successfully posted!');
      console.log(JSON.stringify(result, null, 2));
    } catch (e) {
      if (e.response && e.response.data) {
        console.error('Post error (Detailed):', JSON.stringify(e.response.data, null, 2));
      } else {
        console.error('Post error:', e.message);
      }
    }
    return;
  }

  // ... [Other commands: search, ranking, user, me, feed, following, download]
  // Note: Standard commands implementation follows (simplified for brevity here)
  if (['search', 'ranking', 'user', 'me', 'feed', 'following', 'download'].includes(command)) {
    const pixiv = await getClient();
    if (command === 'search') {
      const results = await (new Illusts(pixiv)).searchIllusts(args[1], parseInt(args[2] || '1'));
      console.log(JSON.stringify(results.slice(0, 10), null, 2));
    } else if (command === 'ranking') {
      const results = await (new Illusts(pixiv)).getRankingIllusts(args[1] || 'day', parseInt(args[2] || '1'));
      console.log(JSON.stringify(results.slice(0, 10), null, 2));
    } else if (command === 'user') {
      const profile = await (new Users(pixiv)).getUser(parseInt(args[1]));
      console.log(JSON.stringify(profile, null, 2));
    } else if (command === 'me') {
      const profile = await (new Account(pixiv)).getSelfUser();
      console.log(JSON.stringify(profile, null, 2));
    } else if (command === 'feed') {
      const results = await (new Account(pixiv)).getFollowIllusts(args[1] || 'all', parseInt(args[2] || '1'));
      console.log(JSON.stringify(results.slice(0, 10), null, 2));
    } else if (command === 'download') {
      const id = parseInt(args[1]);
      const illust = await (new Illusts(pixiv)).getIllustById(id);
      const targetDir = path.join(DOWNLOAD_DIR, String(id));
      if (!fs.existsSync(targetDir)) fs.mkdirSync(targetDir, { recursive: true });
      const files = [];

      // Single image
      if (illust.meta_single_page?.original_image_url) {
        const url = illust.meta_single_page.original_image_url;
        const filepath = path.join(targetDir, path.basename(url));
        await downloadFile(url, filepath, pixiv.accessToken);
        files.push(filepath);
      }

      // Multi-page (manga / gallery)
      if (Array.isArray(illust.meta_pages) && illust.meta_pages.length > 0) {
        for (let i = 0; i < illust.meta_pages.length; i++) {
          const url = illust.meta_pages[i]?.image_urls?.original;
          if (!url) continue;
          const filename = path.basename(url);
          const filepath = path.join(targetDir, filename);
          await downloadFile(url, filepath, pixiv.accessToken);
          files.push(filepath);
        }
      }

      console.log(JSON.stringify({ id: illust.id, title: illust.title, files }, null, 2));
    }
    return;
  }
  
  console.log('Usage: node pixiv-cli.js <login|post|search|ranking|user|me|feed|following|download>');
}

main();
