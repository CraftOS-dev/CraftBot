import sys
import json
import requests
import os


def baidu_search(api_key, requestBody: dict):
    url = "https://qianfan.baidubce.com/v2/ai_search/web_search"

    headers = {
        "Authorization": "Bearer %s" % api_key,
        "X-Appbuilder-From": "openclaw",
        "Content-Type": "application/json"
    }

    # 使用POST方法发送JSON数据
    response = requests.post(url, json=requestBody, headers=headers)
    response.raise_for_status()
    results = response.json()
    if "code" in results:
        raise Exception(results["message"])
    datas = results["references"]
    keys_to_remove = {"snippet"}
    for item in datas:
        for key in keys_to_remove:
            if key in item:
                del item[key]
    return datas


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python baidu_search.py <query>")
        sys.exit(1)

    query = sys.argv[1]
    parse_data = {}
    try:
        parse_data = json.loads(query)
        print(f"success parse request body: {parse_data}")
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")

    if "query" not in parse_data:
        print("Error: query must be present in request body.")
        sys.exit(1)

    # We will pass these via env vars for security
    api_key = os.getenv("BAIDU_API_KEY")

    if not api_key:
        print("Error: BAIDU_API_KEY must be set in environment.")
        sys.exit(1)

    request_body = {
        "messages": [
            {
                "content": parse_data["query"],
                "role": "user"
            }
        ],
        "edition": parse_data["edition"] if "edition" in parse_data else "standard",
        "search_source": "baidu_search_v2",
        "resource_type_filter": parse_data["resource_type_filter"] if "resource_type_filter" in parse_data else [
            {"type": "web", "top_k": 20}],
        "search_filter": parse_data["search_filter"] if "search_filter" in parse_data else {},
        "block_websites": parse_data["block_websites"] if "block_websites" in parse_data else None,
        "search_recency_filter": parse_data[
            "search_recency_filter"] if "search_recency_filter" in parse_data else "year",
        "safe_search": parse_data["safe_search"] if "safe_search" in parse_data else False,
    }
    try:
        results = baidu_search(api_key, request_body)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
