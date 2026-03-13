import os
import sys
import requests
import json
import argparse

URL_PREFIX = "https://qianfan.baidubce.com/v2/tools/ai_ppt/"


class Style:
    def __init__(self, style_id, tpl_id):
        self.style_id = style_id
        self.tpl_id = tpl_id


class Outline:
    def __init__(self, chat_id, query_id, title, outline):
        self.chat_id = chat_id
        self.query_id = query_id
        self.title = title
        self.outline = outline


def get_ppt_theme(api_key: str):
    headers = {
        "Authorization": "Bearer %s" % api_key,
    }
    response = requests.post(URL_PREFIX + "get_ppt_theme", headers=headers)
    result = response.json()
    if "errno" in result and result["errno"] != 0:
        raise RuntimeError(result["errmsg"])
    themes = []
    count = 0
    for theme in result["data"]["ppt_themes"]:
        count += 1
        if count > 20:
            break
        themes.append({
            "style_name_list": theme["style_name_list"],
            "style_id": theme["style_id"],
            "tpl_id": theme["tpl_id"],
        })
    return Style(style_id=themes[0]["style_id"], tpl_id=themes[0]["tpl_id"])


def ppt_outline_generate(api_key: str, query: str):
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "X-Appbuilder-From": "openclaw",
        "Content-Type": "application/json"
    }
    headers.setdefault('Accept', 'text/event-stream')
    headers.setdefault('Cache-Control', 'no-cache')
    headers.setdefault('Connection', 'keep-alive')
    params = {
        "query": query,
    }
    title = ""
    outline = ""
    chat_id = ""
    query_id = ""
    with requests.post(URL_PREFIX + "generate_outline", headers=headers, json=params, stream=True) as response:
        for line in response.iter_lines():
            line = line.decode('utf-8')
            if line and line.startswith("data:"):
                data_str = line[5:].strip()
                delta = json.loads(data_str)
                if not title:
                    title = delta["title"]
                    chat_id = delta["chat_id"]
                    query_id = delta["query_id"]
                outline += delta["outline"]

    return Outline(chat_id=chat_id, query_id=query_id, title=title, outline=outline)


def ppt_generate(api_key: str, query: str, web_content: str = None):
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "Content-Type": "application/json"
    }
    style = get_ppt_theme(api_key)
    outline = ppt_outline_generate(api_key, query)
    headers.setdefault('Accept', 'text/event-stream')
    headers.setdefault('Cache-Control', 'no-cache')
    headers.setdefault('Connection', 'keep-alive')
    params = {
        "query_id": int(outline.query_id),
        "chat_id": int(outline.chat_id),
        "query": query,
        "outline": outline.outline,
        "title": outline.title,
        "style_id": style.style_id,
        "tpl_id": style.tpl_id,
        "web_content": web_content
    }
    with requests.post(URL_PREFIX + "generate_ppt_by_outline", headers=headers, json=params, stream=True) as response:
        if response.status_code != 200:
            print("request failed, status code is %s, error message is %s", response.status_code, response.content)
            return []
        for line in response.iter_lines():
            line = line.decode('utf-8')
            if line and line.startswith("data:"):
                data_str = line[5:].strip()
                yield json.loads(data_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ppt outline generate input parameters")
    parser.add_argument("--query", "-q", type=str, required=True, help="user origin query")
    parser.add_argument("--web_content", "-wc", type=str, default=None, help="web content")
    args = parser.parse_args()

    api_key = os.getenv("BAIDU_API_KEY")
    if not api_key:
        print("Error: BAIDU_API_KEY  must be set in environment.")
        sys.exit(1)
    try:
        print(args.query, args.web_content)
        results = ppt_generate(api_key, args.query, args.web_content)
        for result in results:
            if "is_end" in result and result["is_end"]:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print({"status": result["status"]})
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(f"error type：{exc_type}")
        print(f"error message：{exc_value}")
        sys.exit(1)
