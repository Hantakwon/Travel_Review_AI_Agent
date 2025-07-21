import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import time
import json
import re
from urllib.parse import quote, urljoin
import random
from typing import List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TravelRecommendationAgent:
    def __init__(self, api_key: str, headless: bool = True):
        """
        Gemini AI를 이용한 여행지 추천 에이전트 초기화
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.headless = headless
        self.driver = None
        self.setup_driver()
    
    def setup_driver(self):
        """
        Selenium WebDriver 설정
        """
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(10)
            logger.info("WebDriver 초기화 완료")
            
        except Exception as e:
            logger.error(f"WebDriver 초기화 실패: {e}")
            raise
    
    def get_travel_destinations(self, region: str) -> List[str]:
        """
        지역을 입력받아 여행지 5개를 추천받음
        """
        prompt = f"""
        대한민국 {region} 지역의 유명한 여행지 5개를 추천해주세요.
        다음 형식으로만 답변해주세요:
        1. 여행지명1
        2. 여행지명2
        3. 여행지명3
        4. 여행지명4
        5. 여행지명5
        
        각 여행지명은 한 줄에 하나씩, 숫자와 점만 붙이고 추가 설명은 하지 마세요.
        """
        
        try:
            response = self.model.generate_content(prompt)
            destinations = []
            
            for line in response.text.strip().split('\n'):
                if line.strip():
                    # 숫자와 점을 제거하고 여행지명만 추출
                    destination = re.sub(r'^\d+\.\s*', '', line.strip())
                    if destination:
                        destinations.append(destination)
            
            return destinations[:5]  # 최대 5개만 반환
            
        except Exception as e:
            logger.error(f"여행지 추천 중 오류 발생: {e}")
            # 기본 여행지 반환
            default_destinations = {
                "서울": ["경복궁", "명동", "홍대", "강남", "한강공원"],
                "부산": ["해운대", "광안리", "태종대", "감천문화마을", "자갈치시장"],
                "경주": ["불국사", "석굴암", "첨성대", "안압지", "대릉원"]
            }
            return default_destinations.get(region, ["시청", "역사", "공원", "시장", "문화센터"])
    
    def search_naver_place(self, destination: str, region: str) -> str:
        """
        네이버에서 장소 검색하여 플레이스 URL 찾기 (리뷰 탭으로 이동)
        """
        try:
            search_query = f"{region} {destination}"
            search_url = f"https://search.naver.com/search.naver?query={quote(search_query)}"
            
            logger.info(f"검색 중: {search_query}")
            self.driver.get(search_url)
            time.sleep(2)
            
            # 플레이스 링크 찾기
            place_selectors = [
                "a[href*='place.naver.com']",
                "a[href*='/place/']",
                ".place_bluelink a"
            ]
            
            for selector in place_selectors:
                try:
                    place_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if place_elements:
                        place_url = place_elements[0].get_attribute("href")
                        logger.info(f"플레이스 URL 찾음 (원본): {place_url}")
                        
                        # 🔁 리뷰 탭으로 강제 변경
                        if "placePath=" in place_url:
                            place_url = re.sub(r'placePath=[^&]*', 'placePath=/review', place_url)
                        else:
                            place_url += "&placePath=/review"

                        logger.info(f"리뷰 탭 URL로 변경됨: {place_url}")
                        return place_url
                except:
                    continue
            
            logger.warning(f"플레이스 URL을 찾을 수 없음: {destination}")
            return None
            
        except Exception as e:
            logger.error(f"네이버 플레이스 검색 중 오류: {e}")
            return None

    def crawl_reviews(self, place_url: str, max_reviews: int = 10) -> list[str]:
        if not place_url:
            return []

        reviews = []

        try:
            logger.info(f"리뷰 크롤링 시작: {place_url}")
            self.driver.get(place_url)

            # iframe 진입
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, "entryIframe"))
                )
                logger.info("iframe(entryIframe) 진입 완료")
            except TimeoutException:
                logger.warning("iframe 진입 실패 - entryIframe 없음")
                return []

            # 1차 시도: 기존 CSS 셀렉터들
            review_selectors = [
                ".zPfVt",
                ".YEtwtZFlx",
                "span.Wzv5Z90S4",
            ]

            for selector in review_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"리뷰 요소 찾음: {len(elements)}개 (selector: {selector})")
                        for el in elements:
                            text = el.text.strip()
                            if text and len(text) > 10:
                                reviews.append(text)
                                if len(reviews) >= max_reviews:
                                    break
                        if reviews:
                            break  # 성공했으면 다음 단계 안감
                except:
                    continue

            # 2차 시도: ul#_review_list 내부 a[role="button"][data-pui-click-code="rvshowless"]
            if not reviews:
                try:
                    # 리뷰 a 태그 찾기
                    a_tags = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        'ul#_review_list a[role="button"][data-pui-click-code="rvshowless"]'
                    )
                    logger.info(f"[ul#_review_list] 방식으로 리뷰 {len(a_tags)}개 탐색")

                    for a in a_tags:
                        try:
                            html_content = a.get_attribute("innerHTML")
                            # <br> 태그를 줄바꿈으로 변경하고 텍스트 추출
                            cleaned = html_content.replace("<br>", "\n").replace("&nbsp;", " ").strip()

                            # HTML entity 디코딩
                            from html import unescape
                            text = unescape(cleaned)

                            # 필터링: 의미 있는 리뷰인지 확인
                            if (
                                text and len(text) > 20 and len(text) < 1000 and
                                any(kw in text for kw in ['맛있', '좋았', '추천', '별로', '다시', '친절', '분위기', '최고', '재밌', '흥미'])
                            ):
                                reviews.append(text)
                                if len(reviews) >= max_reviews:
                                    break
                        except Exception as e:
                            logger.debug(f"[리뷰 추출 실패] {e}")
                            continue
                except Exception as e:
                    logger.warning(f"[ul#_review_list 방식 실패] {e}")

            # 3차 시도: 전체 페이지 텍스트에서 필터링
            if not reviews:
                logger.info("리뷰 요소를 찾지 못해 전체 텍스트에서 리뷰 유사 문장 탐색 시도 중...")
                try:
                    all_texts = self.driver.find_elements(By.XPATH, "//*[text()]")
                    for el in all_texts:
                        try:
                            text = el.text.strip()
                            if 20 < len(text) < 500 and any(kw in text for kw in ['좋다', '추천', '별로', '맛있', '친절', '다시']):
                                reviews.append(text)
                                if len(reviews) >= max_reviews:
                                    break
                        except:
                            continue
                except:
                    pass

            logger.info(f"총 {len(reviews)}개의 리뷰 수집 완료")

            # 중복 제거
            seen = set()
            unique_reviews = []
            for r in reviews:
                if r not in seen:
                    unique_reviews.append(r)
                    seen.add(r)

            return unique_reviews[:max_reviews]

        except Exception as e:
            logger.error(f"리뷰 크롤링 중 오류: {e}")
            return []

        finally:
            try:
                self.driver.switch_to.default_content()
            except:
                pass
    
    def analyze_reviews_and_recommend(self, destination: str, reviews: List[str]) -> str:
        """
        리뷰를 분석하여 여행지 추천 생성
        """
        if not reviews:
            return f"'{destination}'에 대한 리뷰를 찾을 수 없어 상세한 분석을 제공할 수 없습니다. 하지만 이 곳은 {destination} 지역의 인기 여행지 중 하나입니다."
        
        reviews_text = "\n".join([f"- {review}" for review in reviews])
        
        prompt = f"""
        다음은 '{destination}' 여행지에 대한 실제 방문객 리뷰들입니다:

        {reviews_text}

        이 리뷰들을 바탕으로 다음 내용을 포함한 여행지 추천글을 작성해주세요:
        1. 이 여행지의 주요 매력 포인트
        2. 어떤 사람들에게 추천하는지 (가족, 연인, 친구, 혼자 등)
        3. 방문 시 주의사항이나 팁
        4. 전체적인 추천도 (5점 만점)

        친근하고 도움이 되는 톤으로 작성해주세요.
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"리뷰 분석 중 오류: {e}")
            return f"'{destination}'는 수집된 리뷰를 바탕으로 볼 때 방문할 만한 가치가 있는 여행지입니다."
    
    def run_agent_loop(self):
        """
        AI 에이전트 메인 루프 실행
        """
        print("AI 여행지 추천 에이전트가 시작되었습니다!")
        print("네이버 플레이스에서 리뷰를 크롤링하여 분석합니다.")
        print("=" * 50)
        
        while True:
            try:
                # 1. 사용자 입력 받기
                print("\n📍 대한민국 내 지역을 입력해주세요 (예: 서울, 부산, 경주)")
                print("종료하려면 'quit' 또는 'exit'를 입력하세요.")
                
                region = input("지역명: ").strip()
                
                if region.lower() in ['quit', 'exit', '종료']:
                    print("AI 에이전트를 종료합니다. 좋은 여행 되세요!")
                    break
                
                if not region:
                    print("❌ 지역명을 입력해주세요.")
                    continue
                
                print(f"\n🔍 {region} 지역의 여행지를 찾고 있습니다...")
                
                # 2. 여행지 5개 추천받기
                destinations = self.get_travel_destinations(region)
                
                if not destinations:
                    print("❌ 여행지를 찾을 수 없습니다. 다른 지역을 시도해보세요.")
                    continue
                
                print(f"\n {region} 지역 추천 여행지:")
                for i, dest in enumerate(destinations, 1):
                    print(f"   {i}. {dest}")
                
                print(f"\n 각 여행지의 네이버 플레이스에서 실제 리뷰를 수집하고 분석합니다...")
                print("이 과정은 몇 분 정도 소요될 수 있습니다.")
                print("=" * 50)
                
                # 3. 각 여행지에 대한 리뷰 크롤링 및 분석
                for i, destination in enumerate(destinations, 1):
                    print(f"\n🏛️  {i}. {destination}")
                    print("-" * 30)
                    
                    # 네이버 플레이스 검색
                    place_url = self.search_naver_place(destination, region)
                    
                    if place_url:
                        print(f"🔗 플레이스 URL: {place_url}")
                        
                        # 리뷰 크롤링
                        print("📝 리뷰 수집 중...")
                        reviews = self.crawl_reviews(place_url, max_reviews=10)
                        
                        if reviews:
                            print(f"✅ {len(reviews)}개의 리뷰를 수집했습니다.")
                            print("🤖 AI가 리뷰를 분석하여 추천글을 생성 중...")
                            
                            # 수집된 리뷰 일부 표시
                            print("\n📄 수집된 리뷰 샘플:")
                            for j, review in enumerate(reviews[:3], 1):
                                print(f"   {j}. {review[:100]}{'...' if len(review) > 100 else ''}")
                            
                            recommendation = self.analyze_reviews_and_recommend(destination, reviews)
                            print(f"\n🎯 AI 추천 분석 결과:")
                            print(f"{recommendation}")
                        else:
                            print("❌ 리뷰를 수집할 수 없습니다.")
                            print("네이버 플레이스 페이지 구조가 변경되었거나 리뷰가 없을 수 있습니다.")
                    else:
                        print("❌ 네이버 플레이스를 찾을 수 없습니다.")
                    
                    print("\n" + "="*50)
                    time.sleep(3)  # 요청 간격 조절
                
                print(f"\n✅ {region} 지역 여행지 추천이 완료되었습니다!")
                print("다른 지역도 검색해보세요! 🌟")
                
            except KeyboardInterrupt:
                print("\n\n👋 사용자가 종료를 요청했습니다.")
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                print(f"\n❌ 오류가 발생했습니다: {e}")
                print("다시 시도해주세요.")
    
    def __del__(self):
        """
        소멸자: WebDriver 정리
        """
        if self.driver:
            try:
                self.driver.quit()
                logger.info("WebDriver 종료 완료")
            except:
                pass

def main():
    """
    메인 실행 함수
    """
    print("🔑 Google Gemini API 키를 입력해주세요:")
    api_key = input("API Key: ").strip()
    
    if not api_key:
        print("❌ API 키가 필요합니다.")
        return
    
    print("\n🖥️  브라우저 모드를 선택하세요:")
    print("1. Headless 모드 (백그라운드 실행, 빠름)")
    print("2. 브라우저 표시 모드 (크롤링 과정 확인 가능)")
    
    mode_choice = input("선택 (1 또는 2): ").strip()
    headless = mode_choice != "2"
    
    try:
        # AI 에이전트 초기화 및 실행
        agent = TravelRecommendationAgent(api_key, headless=headless)
        agent.run_agent_loop()
        
    except Exception as e:
        logger.error(f"에이전트 초기화 중 오류: {e}")
        print(f"❌ 에이전트 초기화 중 오류: {e}")
        print("Chrome WebDriver가 설치되어 있는지 확인하고 다시 시도해주세요.")

if __name__ == "__main__":
    # 필요한 패키지 설치 안내
    required_packages = [
        "google-generativeai",
        "requests", 
        "beautifulsoup4",
        "selenium"
    ]
    
    print("📦 필요한 패키지들:")
    print("pip install " + " ".join(required_packages))
    print("\n🔧 Chrome WebDriver 설치 필요:")
    print("1. Chrome 브라우저 설치")
    print("2. ChromeDriver 다운로드: https://chromedriver.chromium.org/")
    print("3. ChromeDriver를 PATH에 추가하거나 현재 디렉토리에 배치")
    print("\n" + "="*50)
    
    main()