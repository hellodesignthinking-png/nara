"""
국내 문화예술·공공기관 실제 공고 수집 모듈

웹 스크래핑(requests + BeautifulSoup) 및 공공데이터포털 API를 활용하여
실제 공고 데이터를 수집합니다.

지원 플랫폼:
  - 아르코 (ARKO): 웹 스크래핑
  - 서울문화재단 (SFAC): 웹 스크래핑
  - 콘텐츠진흥원 (KOCCA): 공공데이터포털 API
  - 예술경영지원센터 (GOKAMS): 웹 스크래핑
  - 공예디자인진흥원 (KCDF): 웹 스크래핑
  - K-Startup: 공공데이터포털 API
  - 한국관광공사: 웹 스크래핑
  - LH: 웹 스크래핑
  - 한국연구재단 (NRF): 웹 스크래핑
  - e나라도움: 공공데이터포털 API
"""

import logging
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.models.schemas import BidAnnouncement

logger = logging.getLogger(__name__)

# 공통 User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 15


class CultureBidCollector:
    """국내 문화예술 기관 공고 실데이터 수집기"""

    def __init__(self, config):
        self.config = config
        self.api_key = getattr(config, 'data_go_kr_api_key', '') or ''
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        })

    def _safe_request(self, url, params=None, method='GET'):
        """안전한 HTTP 요청 (재시도 포함)"""
        for attempt in range(2):
            try:
                if method == 'GET':
                    resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                else:
                    resp = self.session.post(url, data=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp
            except Exception as e:
                logger.warning("%s 요청 실패 (시도 %d/2): %s", url[:60], attempt + 1, e)
                if attempt == 0:
                    time.sleep(1)
        return None

    def _to_bid(self, data: dict) -> BidAnnouncement:
        """dict → BidAnnouncement 변환"""
        bid = BidAnnouncement.from_dict(data)
        bid.collected_at = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        return bid

    # ═══════════════════════════════════════════
    # 1. 아르코 (ARKO) — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_arko(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """한국문화예술위원회 입찰/공모 공고 수집"""
        bids = []
        base_url = "https://www.arko.or.kr/board/list/4006"

        try:
            resp = self._safe_request(base_url)
            if not resp:
                logger.error("ARKO: 페이지 접속 실패")
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            # 게시판 테이블 또는 리스트 찾기
            rows = soup.select('table tbody tr') or soup.select('.board-list li, .bbs-list li, .list-body li')

            if not rows:
                # 구조가 다를 수 있으니 대체 선택자 시도
                rows = soup.select('tr[class], div.list-item, div.bbs-item')

            if not rows:
                logger.warning("ARKO: 공고 목록을 찾을 수 없음 (HTML 구조 변경?)")
                return []

            for i, row in enumerate(rows[:20]):
                try:
                    # 제목과 링크 추출
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue

                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://www.arko.or.kr{href}"

                    # 날짜 추출
                    date_text = ""
                    tds = row.select('td')
                    for td in tds:
                        text = td.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    if not date_text:
                        # span이나 다른 태그에서 날짜 찾기
                        for el in row.select('span, em, p'):
                            text = el.get_text(strip=True)
                            if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                                date_text = text.replace('.', '-').replace('/', '-')
                                break

                    bid_data = {
                        "bid_ntce_no": f"ARKO-REAL-{date_text.replace('-', '')}-{i:03d}" if date_text else f"ARKO-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "한국문화예술위원회",
                        "demand_org_name": "한국문화예술위원회",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "bid_close_dt": "",
                        "category": "문화예술",
                        "bid_method": "공모",
                        "contract_method": "",
                        "region": "전국",
                        "license_limit": "",
                        "rfp_url": href,
                        "rfp_text": ""
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception as e:
                    logger.debug("ARKO: 행 파싱 오류: %s", e)
                    continue

            logger.info("ARKO: 실제 공고 %d건 수집 완료", len(bids))
        except Exception as e:
            logger.error("ARKO: 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 2. 서울문화재단 (SFAC) — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_sfac(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """서울문화재단 공고/공모 수집"""
        bids = []
        base_url = "https://www.sfac.or.kr/sfac/simplyboard/list.do"
        params = {"bbsId": "OPEN01", "pageIndex": "1"}

        try:
            resp = self._safe_request(base_url, params=params)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            rows = (soup.select('table tbody tr') or
                    soup.select('.board_list li, .bbs-list li') or
                    soup.select('.list-table tbody tr'))

            if not rows:
                logger.warning("SFAC: 공고 목록을 찾을 수 없음")
                return []

            for i, row in enumerate(rows[:15]):
                try:
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://www.sfac.or.kr{href}"

                    date_text = ""
                    for el in row.select('td, span, em'):
                        text = el.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    bid_data = {
                        "bid_ntce_no": f"SFAC-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "서울문화재단",
                        "demand_org_name": "서울문화재단",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "category": "문화예술", "bid_method": "공모",
                        "region": "서울", "rfp_url": href,
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception:
                    continue

            logger.info("SFAC: 실제 공고 %d건 수집 완료", len(bids))
        except Exception as e:
            logger.error("SFAC: 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 3. 콘텐츠진흥원 (KOCCA) — 공공데이터포털 API
    # ═══════════════════════════════════════════
    def collect_kocca(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """한국콘텐츠진흥원 지원사업 공고 — 공공데이터포털 API"""
        if not self.api_key:
            logger.warning("KOCCA: API 키 미설정 — 건너뜁니다.")
            return []

        bids = []
        api_url = "https://apis.data.go.kr/B553668/koccaBsnsPbanc/list"

        try:
            params = {
                "serviceKey": self.api_key,
                "dataType": "JSON",
                "numOfRows": "20",
                "pageNo": "1",
            }
            resp = self._safe_request(api_url, params=params)
            if not resp:
                return []

            data = resp.json()
            items = []
            # 공공데이터포털 표준 응답 파싱
            body = data.get('response', {}).get('body', {})
            if body:
                items_raw = body.get('items', body.get('item', []))
                if isinstance(items_raw, dict):
                    items_raw = items_raw.get('item', [])
                if isinstance(items_raw, dict):
                    items_raw = [items_raw]
                items = items_raw if isinstance(items_raw, list) else []
            else:
                # 다른 응답 형식일 수 있음
                items = data.get('data', data.get('items', []))
                if isinstance(items, dict):
                    items = [items]

            for i, item in enumerate(items[:20]):
                title = item.get('pbancNm', item.get('title', item.get('bsnsPbancNm', '')))
                if not title:
                    continue

                begin_dt = item.get('pbancBgngDt', item.get('rcptBgngDt', ''))
                end_dt = item.get('pbancEndDt', item.get('rcptEndDt', ''))
                detail_url = item.get('dtlUrl', item.get('url', 'https://www.kocca.kr'))

                bid_data = {
                    "bid_ntce_no": f"KOCCA-REAL-{item.get('pbancSn', i):04d}" if isinstance(item.get('pbancSn'), int) else f"KOCCA-REAL-{i:04d}",
                    "bid_ntce_ord": "00",
                    "title": title,
                    "org_name": "한국콘텐츠진흥원",
                    "demand_org_name": item.get('jrsdInsttNm', '한국콘텐츠진흥원'),
                    "budget": int(item.get('totBgt', 0) or 0),
                    "bid_begin_dt": begin_dt,
                    "bid_close_dt": end_dt,
                    "category": "콘텐츠",
                    "bid_method": "공모",
                    "region": "전국",
                    "rfp_url": detail_url,
                }
                bids.append(self._to_bid(bid_data))

            logger.info("KOCCA: 공공API 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("KOCCA: API 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 4. e나라도움 — 공공데이터포털 API
    # ═══════════════════════════════════════════
    def collect_e_naradoum(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """e나라도움/보조금24 공모사업 — 공공데이터포털 API"""
        if not self.api_key:
            return []

        bids = []
        api_url = "https://apis.data.go.kr/1371000/sbscrptAnncDetail/getSbscrptAnncList"

        try:
            params = {
                "serviceKey": self.api_key,
                "type": "JSON",
                "numOfRows": "20",
                "pageNo": "1",
            }
            resp = self._safe_request(api_url, params=params)
            if not resp:
                return []

            data = resp.json()
            body = data.get('response', {}).get('body', {})
            items_raw = body.get('items', {})
            if isinstance(items_raw, dict):
                items_raw = items_raw.get('item', [])
            if isinstance(items_raw, dict):
                items_raw = [items_raw]
            items = items_raw if isinstance(items_raw, list) else []

            for i, item in enumerate(items[:20]):
                title = item.get('pbancTtl', item.get('title', ''))
                if not title:
                    continue

                bid_data = {
                    "bid_ntce_no": f"ENARA-REAL-{i:04d}",
                    "bid_ntce_ord": "00",
                    "title": title,
                    "org_name": item.get('insttNm', '보조금24'),
                    "demand_org_name": item.get('bsnsDprtNm', ''),
                    "budget": int(item.get('ttlBgt', 0) or 0),
                    "bid_begin_dt": item.get('rcptBgngDt', ''),
                    "bid_close_dt": item.get('rcptEndDt', ''),
                    "category": "보조금", "bid_method": "공모", "region": "전국",
                    "rfp_url": "https://www.gosims.go.kr",
                }
                bids.append(self._to_bid(bid_data))

            logger.info("e나라도움: 공공API 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("e나라도움: API 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 5. 예술경영지원센터 (GOKAMS) — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_gokams(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """예술경영지원센터 공지/공모 수집"""
        bids = []
        base_url = "https://www.gokams.or.kr/01_news/notice_list.aspx"

        try:
            resp = self._safe_request(base_url)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            rows = (soup.select('table tbody tr') or
                    soup.select('.board-list li, .bbs-list li, .list-body li') or
                    soup.select('.board_list tr'))

            if not rows:
                return []

            for i, row in enumerate(rows[:15]):
                try:
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://www.gokams.or.kr{href}"

                    date_text = ""
                    for el in row.select('td, span, em'):
                        text = el.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    bid_data = {
                        "bid_ntce_no": f"GOKAMS-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "예술경영지원센터",
                        "demand_org_name": "예술경영지원센터",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "category": "문화예술", "bid_method": "공모", "region": "전국",
                        "rfp_url": href,
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception:
                    continue

            logger.info("GOKAMS: 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("GOKAMS: 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 6. 공예디자인진흥원 (KCDF) — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_kcdf(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """한국공예디자인문화진흥원 공지/입찰 수집"""
        bids = []
        base_url = "https://www.kcdf.or.kr/board/list/notice"

        try:
            resp = self._safe_request(base_url)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            rows = (soup.select('table tbody tr') or
                    soup.select('.board_list li, .bbs-list li'))

            if not rows:
                return []

            for i, row in enumerate(rows[:15]):
                try:
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://www.kcdf.or.kr{href}"

                    date_text = ""
                    for el in row.select('td, span, em'):
                        text = el.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    bid_data = {
                        "bid_ntce_no": f"KCDF-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "한국공예디자인문화진흥원",
                        "demand_org_name": "한국공예디자인문화진흥원",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "category": "디자인", "bid_method": "공모", "region": "전국",
                        "rfp_url": href,
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception:
                    continue

            logger.info("KCDF: 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("KCDF: 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 7. 한국관광공사 — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_visitkorea(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """한국관광공사 입찰/공모 수집"""
        bids = []
        base_url = "https://kto.visitkorea.or.kr/kor/biz/announce/announce.kto"

        try:
            resp = self._safe_request(base_url)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            rows = (soup.select('table tbody tr') or
                    soup.select('.board-list li, .list-body li'))

            if not rows:
                return []

            for i, row in enumerate(rows[:15]):
                try:
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://kto.visitkorea.or.kr{href}"

                    date_text = ""
                    for el in row.select('td, span'):
                        text = el.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    bid_data = {
                        "bid_ntce_no": f"KTO-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "한국관광공사",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "category": "관광", "bid_method": "공모", "region": "전국",
                        "rfp_url": href,
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception:
                    continue

            logger.info("관광공사: 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("관광공사: 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 8. LH 한국토지주택공사 — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_lh(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """LH 전자조달 공고 수집"""
        bids = []
        base_url = "https://ebid.lh.or.kr/ebid.et.tp.cmd.BidNoticeListCmd.dev"

        try:
            resp = self._safe_request(base_url)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            rows = (soup.select('table tbody tr') or
                    soup.select('.list-body tr, .board-list li'))

            if not rows:
                return []

            for i, row in enumerate(rows[:15]):
                try:
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://ebid.lh.or.kr{href}"

                    date_text = ""
                    for el in row.select('td, span'):
                        text = el.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    bid_data = {
                        "bid_ntce_no": f"LH-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "한국토지주택공사",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "category": "건설", "bid_method": "일반경쟁", "region": "전국",
                        "rfp_url": href,
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception:
                    continue

            logger.info("LH: 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("LH: 수집 실패: %s", e)
            return []

        return bids

    # ═══════════════════════════════════════════
    # 9. 한국연구재단 (NRF) — 웹 스크래핑
    # ═══════════════════════════════════════════
    def collect_nrf(self, start_date: str = "", end_date: str = "") -> list[BidAnnouncement]:
        """한국연구재단 공고 수집"""
        bids = []
        base_url = "https://www.nrf.re.kr/biz/info/notice/list"

        try:
            resp = self._safe_request(base_url)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, 'lxml')
            rows = (soup.select('table tbody tr') or
                    soup.select('.board-list li, .bbs-list li'))

            if not rows:
                return []

            for i, row in enumerate(rows[:15]):
                try:
                    link_el = row.select_one('a[href]')
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue

                    href = link_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = f"https://www.nrf.re.kr{href}"

                    date_text = ""
                    for el in row.select('td, span'):
                        text = el.get_text(strip=True)
                        if re.match(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text.replace('.', '-').replace('/', '-')
                            break

                    bid_data = {
                        "bid_ntce_no": f"NRF-REAL-{i:04d}",
                        "bid_ntce_ord": "00",
                        "title": title,
                        "org_name": "한국연구재단",
                        "budget": 0,
                        "bid_begin_dt": f"{date_text} 09:00:00" if date_text else "",
                        "category": "연구", "bid_method": "공모", "region": "전국",
                        "rfp_url": href,
                    }
                    bids.append(self._to_bid(bid_data))
                except Exception:
                    continue

            logger.info("NRF: 실제 공고 %d건 수집", len(bids))
        except Exception as e:
            logger.error("NRF: 수집 실패: %s", e)
            return []

        return bids
