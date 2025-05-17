import os
import logging
import random
import time
import json
import schedule
from requests_oauthlib import OAuth1Session
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler()] + ([logging.FileHandler('twitter_bot.log')] if os.environ.get('LOG_FILE') else [])
)

# Twitter Setup
def setup_twitter_oauth():
    logging.info("➡️ Entering setup_twitter_oauth()")
    consumer_key = os.environ.get("TWITTER_API_KEY")
    consumer_secret = os.environ.get("TWITTER_API_SECRET")
    access_token = os.environ.get("TWITTER_ACCESS_TOKEN")
    access_token_secret = os.environ.get("TWITTER_ACCESS_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        logging.error("❌ Missing Twitter API credentials as environment variables.")
        return None

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_token_secret,
    )

# Setup Selenium WebDriver for ChatGPT
def setup_selenium_driver():
    logging.info("➡️ Setting up Selenium WebDriver")
    
    # Configure Chrome options for headless operation
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # For GitHub Actions, we need these additional configurations
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-setuid-sandbox")
        chrome_options.add_argument("--remote-debugging-port=9222")
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        logging.error(f"❌ Failed to initialize Selenium WebDriver: {e}")
        return None

# Login to ChatGPT
def login_to_chatgpt(driver):
    logging.info("➡️ Logging into ChatGPT")
    
    email = os.environ.get("CHATGPT_EMAIL")
    password = os.environ.get("CHATGPT_PASSWORD")
    
    if not email or not password:
        logging.error("❌ Missing ChatGPT credentials in environment variables")
        return False
    
    try:
        # Navigate to ChatGPT login page
        driver.get("https://chat.openai.com/auth/login")
        time.sleep(3)  # Wait for page to load
        
        # Click Log in button
        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Log in')]"))
        )
        login_button.click()
        
        # Enter email
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        email_input.send_keys(email)
        email_input.send_keys(Keys.RETURN)
        
        # Enter password
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)
        
        # Wait for the chat interface to load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//textarea[contains(@placeholder, 'Message ChatGPT')]"))
        )
        
        logging.info("✅ Successfully logged into ChatGPT")
        return True
        
    except Exception as e:
        logging.error(f"❌ Failed to login to ChatGPT: {e}")
        return False

# Generate Tweet using ChatGPT
def generate_tweet_with_chatgpt(driver, topic):
    if not driver:
        logging.error("❌ WebDriver not initialized")
        return None
    
    tweet_styles_str = os.environ.get('TWEET_STYLES')
    tweet_styles = json.loads(tweet_styles_str) if tweet_styles_str else [
        "Share an insightful fact about {topic}. Keep it concise and engaging.",
        "Write a thought-provoking question about {topic} to spark discussion.",
        "Post a quick tip or hack related to {topic}.",
        "Create a short and witty take on {topic}.",
        "Write a motivational quote related to {topic}.",
        "Provide a little-known historical fact about {topic}.",
        "Break down a complex concept related to {topic} in simple terms."
    ]
    
    max_retries = int(os.environ.get('MAX_TWEET_GENERATION_RETRIES', '3'))
    max_length = int(os.environ.get('MAX_TWEET_LENGTH', '280'))
    retry_count = 0
    
    while retry_count < max_retries:
        selected_style = random.choice(tweet_styles).format(topic=topic)
        prompt = f"{selected_style} Make sure your response is under {max_length} characters and contains only the tweet text with no additional explanations or quotes."
        
        try:
            # Find the textarea and enter the prompt
            textarea = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//textarea[contains(@placeholder, 'Message ChatGPT')]"))
            )
            textarea.clear()
            textarea.send_keys(prompt)
            textarea.send_keys(Keys.RETURN)
            
            # Wait for ChatGPT to respond
            response_selector = "div[data-message-author-role='assistant'] div.markdown"
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, response_selector))
            )
            
            # Give a moment for the full response to appear
            time.sleep(3)
            
            # Get the latest response
            responses = driver.find_elements(By.CSS_SELECTOR, response_selector)
            tweet_text = responses[-1].text.strip()
            
            # Clean the tweet text (remove quotes if present)
            tweet_text = tweet_text.strip('"\'')
            
            if len(tweet_text) <= max_length:
                logging.info(f"✅ Generated tweet: {tweet_text}")
                
                # Start a new chat for the next prompt
                new_chat_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'New chat') or contains(@aria-label, 'New chat')]"))
                )
                new_chat_button.click()
                time.sleep(2)  # Wait for new chat to initialize
                
                return tweet_text
            else:
                logging.warning(f"⚠️ Generated tweet exceeds maximum length ({len(tweet_text)} characters). Retrying.")
                retry_count += 1
                
                # Start a new chat for the next attempt
                new_chat_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'New chat') or contains(@aria-label, 'New chat')]"))
                )
                new_chat_button.click()
                time.sleep(2)  # Wait for new chat to initialize
                
        except Exception as e:
            logging.error(f"❌ ChatGPT tweet generation failed (attempt {retry_count + 1}/{max_retries}): {e}")
            retry_count += 1
            
            # Try to start a new chat if possible
            try:
                new_chat_button = driver.find_element(By.XPATH, "//a[contains(text(), 'New chat') or contains(@aria-label, 'New chat')]")
                new_chat_button.click()
                time.sleep(2)
            except:
                pass  # Ignore if we can't find the new chat button
    
    logging.error("❌ Failed to generate a suitable tweet after multiple retries.")
    return None

# Post Tweet
def post_tweet(oauth, tweet_text):
    if not oauth or not tweet_text:
        logging.error("❌ Cannot post tweet. Missing OAuth or tweet text.")
        return
    
    payload = {"text": tweet_text}
    try:
        response = oauth.post("https://api.twitter.com/2/tweets", json=payload)
        if response.status_code != 201:
            logging.error(f"❌ Twitter API error: {response.status_code} {response.text}")
            return
        
        tweet_id = response.json()['data']['id']
        logging.info(f"✅ Tweet posted: {tweet_text} (ID: {tweet_id})")
    except Exception as e:
        logging.error(f"❌ Twitter API error: {e}")

# Main function to generate and post tweet
def generate_and_post(schedule_time, driver):
    logging.info(f"➡️ Attempting to generate and post for schedule time: {schedule_time}")
    oauth = setup_twitter_oauth()
    
    if not oauth:
        logging.error("❌ Twitter OAuth failed.")
        return None
    
    if not driver:
        logging.error("❌ Selenium WebDriver not initialized.")
        return None
    
    topics_str = os.environ.get('TOPICS')
    topics = json.loads(topics_str) if topics_str else [
        "ETL (Extract, Transform, Load) Processes",
        "Data Streaming Technologies",
        "DevOps for Data Science (MLOps)",
        "Internet of Things (IoT) Data Analysis",
        "The aim of Every business data analysis ",
        "Build your Thought process in every data analysis task",
        "Anomaly Detection in Data",
        "Open Source Data Science Tools",
        "Data Science Career Advice",
        "Writing Technical Documentation",
        "SQL Tips for Data Analysts",
        "Machine Learning Model Optimization",
        "Big Data Trends",
        "Most used shortcut in Excel",
        "Data Security and Privacy",
        "Phython Skills for data science",
        "Power BI and Tableau as first choice tools",
        "Feature Engineering in ML",
        "Python Libraries for Data Science",
        "Version Control for Data Projects (Git)",
        "Data Science Project Management"
    ]
    
    topic = random.choice(topics)
    logging.info(f"🔹 Generating tweet for topic: {topic}")
    tweet_text = generate_tweet_with_chatgpt(driver, topic)
    
    if tweet_text:
        logging.info("🔹 Posting tweet now...")
        post_tweet(oauth, tweet_text)
        logging.info("✅ Tweet successfully posted!")
        return tweet_text
    else:
        logging.error("❌ Tweet generation failed for this schedule time.")
        return None

# Scheduled Tweet Posting (for one execution)
def run_scheduled_tweets_once():
    logging.info("✅ run_scheduled_tweets_once() function has started for this execution.")
    
    # Setup Selenium and login to ChatGPT once for the entire session
    driver = setup_selenium_driver()
    if not driver:
        logging.error("❌ Failed to set up Selenium WebDriver. Exiting.")
        return []
    
    # Login to ChatGPT
    login_success = login_to_chatgpt(driver)
    if not login_success:
        logging.error("❌ Failed to log in to ChatGPT. Exiting.")
        driver.quit()
        return []
    
    schedule_times_str = os.environ.get('SCHEDULE_TIMES', '["07:00", "13:00", "19:00"]')
    schedule_times = json.loads(schedule_times_str)
    tweets_to_post = []
    
    try:
        # For immediate testing, generate and post a tweet right away
        if os.environ.get('POST_IMMEDIATELY', 'false').lower() == 'true':
            logging.info("🔹 Posting a tweet immediately")
            tweet = generate_and_post("immediate", driver)
            if tweet:
                tweets_to_post.append(tweet)
        
        # Schedule regular posts
        for time_str in schedule_times:
            try:
                schedule.every().day.at(time_str).do(lambda t=time_str: tweets_to_post.append(generate_and_post(t, driver)))
                logging.info(f"⏰ Scheduled generation for {time_str}")
            except schedule.InvalidTimeError:
                logging.error(f"❌ Invalid schedule time: {time_str}")
        
        # Run pending scheduled tasks for a limited duration
        duration_hours = float(os.environ.get('RUN_DURATION_HOURS', '5'))
        end_time = time.time() + (duration_hours * 60 * 60)
        while time.time() < end_time and schedule.get_jobs():
            schedule.run_pending()
            time.sleep(1)
        
    except Exception as e:
        logging.error(f"❌ Error during scheduled tweets: {e}")
    finally:
        # Always close the driver when done
        if driver:
            driver.quit()
            logging.info("👋 Closed Selenium WebDriver")
    
    logging.info("✅ Scheduled tasks completed for this execution.")
    return [tweet for tweet in tweets_to_post if tweet is not None]

if __name__ == "__main__":
    logging.info("🚀 Running Twitter bot with Selenium for ChatGPT...")
    try:
        run_scheduled_tweets_once()
    except Exception as e:
        logging.error(f"❌ Error in run_scheduled_tweets_once: {e}")
