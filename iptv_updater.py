import os
import re
import time
import requests
import concurrent.futures
import uuid
import logging
from urllib.parse import urljoin, urlparse, urlunparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ======================
# 配置参数（可根据需要调整）
# ======================
MAX_WORKERS = 15
SPEED_THRESHOLD = 0.3  # 提高速度阈值
REQUEST_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
RETRY_STRATEGY = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)

# 初始化日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('iptv_updater.log'),
        logging.StreamHandler()
    ]
)

class ReliableIPTVUpdater:
    def __init__(self):
        self.channels = []
        self.session = self._create_session()
        self.sources = [
            "https://d.kstore.dev/download/10694/zmtvid.txt",
            
        ]
        self.backup_sources = [
            
        ]
        self.output_file = "zby.txt"
        self.build_id = uuid.uuid4().hex[:8]

    def _create_session(self):
        """创建带重试机制的会话"""
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=RETRY_STRATEGY)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept-Encoding': 'gzip, deflate'
        })
        return session

    def _fetch_source(self, url):
        """获取源数据并处理异常"""
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.warning(f"源获取失败 [{url}]: {str(e)}")
            return None

    def _extract_urls(self, text):
        """使用多模式匹配URL"""
        patterns = [
            r"(https?://\S+?\.m3u8?\b)",
            r"#EXTINF:-1.*?(http[^\s]+)",
            r"(?:host|url)\s*=\s*['\"](http[^'\"]]+)"
        ]
        urls = set()
        for pattern in patterns:
            urls.update(re.findall(pattern, text, re.I))
        return [self._normalize_url(u) for u in urls if u]

    def _normalize_url(self, raw_url):
        """标准化API地址"""
        try:
            parsed = urlparse(raw_url)
            if not parsed.netloc:
                return None
            return urlunparse((
                parsed.scheme or 'http',
                parsed.netloc,
                '/iptv/live/1000.json',
                '',
                'key=txiptv',
                ''
            ))
        except:
            return None

    def _speed_test(self, url):
        """改进的测速方法"""
        try:
            start = time.time()
            with self.session.get(url, stream=True, timeout=10) as r:
                r.raise_for_status()
                content_length = int(r.headers.get('Content-Length', 102400))
                chunk_size = 4096
                for _ in r.iter_content(chunk_size=chunk_size):
                    if time.time() - start > 8:
                        break
                duration = max(time.time() - start, 0.1)
                return (content_length / 1024) / duration
        except Exception as e:
            logging.debug(f"测速失败 [{url}]: {str(e)}")
            return 0

    def _process_api(self, api_url):
        """处理API端点并捕获所有异常"""
        try:
            logging.info(f"正在处理API端点: {api_url}")
            response = self.session.get(api_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            try:
                data = response.json()
                if not isinstance(data.get('data'), list):
                    raise ValueError("无效的JSON结构")
            except ValueError:
                logging.warning(f"JSON解析失败 [{api_url}]")
                return

            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = []
                for channel in data['data']:
                    if not all(k in channel for k in ('name', 'url')):
                        continue
                    try:
                        full_url = urljoin(api_url, channel['url'])
                        futures.append((
                            channel['name'],
                            full_url,
                            executor.submit(self._speed_test, full_url)
                        ))
                    except Exception as e:
                        logging.error(f"URL处理错误: {str(e)}")

                for name, url, future in futures:
                    try:
                        speed = future.result()
                        if speed >= SPEED_THRESHOLD:
                            self.channels.append(f"{name},{url}")
                            logging.info(f"有效频道: {name} ({speed:.2f} KB/s)")
                        else:
                            logging.debug(f"速度不足: {name} ({speed:.2f} KB/s)")
                    except Exception as e:
                        logging.error(f"测速异常: {str(e)}")

        except requests.RequestException as e:
            logging.error(f"请求失败 [{api_url}]: {str(e)}")
        except Exception as e:
            logging.error(f"处理异常: {str(e)}")

    def _save_channels(self):
        """可靠的文件保存方法"""
        try:
            # 确保输出目录存在
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
            
            # 分类处理
            categorized = {"CCTV": [], "卫视": [], "其他": []}
            cctv_pattern = re.compile(r"CCTV[\-\s]?(\d{1,2}\+?|4K|8K|HD)", re.I)
            
            for line in set(self.channels):
                name, url = line.split(',', 1)
                if cctv_pattern.search(name):
                    categorized["CCTV"].append(line)
                elif "卫视" in name:
                    categorized["卫视"].append(line)
                else:
                    categorized["其他"].append(line)
            
            # 排序逻辑
            def cctv_sort(item):
                return int(re.search(r"\d+", item).group() or 999
            
            # 写入文件
            with open(self.output_file, "w", encoding="utf-8") as f:
                f.write(f"# 最后更新: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 构建ID: {self.build_id}\n\n")
                
                f.write("央视频道,#genre#\n")
                f.write("\n".join(sorted(categorized["CCTV"], key=cctv_sort)) 
                f.write("\n\n卫视频道,#genre#\n")
                f.write("\n".join(sorted(categorized["卫视"])))
                f.write("\n\n其他频道,#genre#\n")
                f.write("\n".join(sorted(categorized["其他"])))
            
            # 验证文件
            self._validate_output()

        except Exception as e:
            logging.error(f"文件保存失败: {str(e)}")
            raise

    def _validate_output(self):
        """增强的文件验证"""
        if not os.path.exists(self.output_file):
            raise FileNotFoundError("输出文件不存在")
            
        with open(self.output_file, "r", encoding="utf-8") as f:
            content = f.read()
            if len(content) < 500:
                raise ValueError("文件内容过短")
            if content.count("#genre#") != 3:
                raise ValueError("分类标签缺失")
                
        logging.info(f"文件验证通过: {os.path.abspath(self.output_file)}")

    def run(self):
        """主运行逻辑"""
        try:
            logging.info("=== IPTV更新程序启动 ===")
            
            # 阶段1：收集源
            all_urls = set()
            for source in self.sources + self.backup_sources:
                if content := self._fetch_source(source):
                    all_urls.update(self._extract_urls(content))
            logging.info(f"发现有效API端点: {len(all_urls)}个")
            
            # 阶段2：处理API
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                list(executor.map(self._process_api, all_urls))
            
            # 阶段3：保存结果
            self._save_channels()
            logging.info(f"成功更新 {len(self.channels)} 个频道")
            return True
            
        except Exception as e:
            logging.error(f"程序运行失败: {str(e)}")
            return False

if __name__ == "__main__":
    updater = ReliableIPTVUpdater()
    if updater.run():
        exit(0)
    else:
        exit(1)


