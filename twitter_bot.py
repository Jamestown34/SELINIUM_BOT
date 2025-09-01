import os
import logging
import random
import time
import json
import schedule
import requests
from requests_oauthlib import OAuth1Session
from datetime import datetime, timedelta
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler()] + ([logging.FileHandler('twitter_bot.log')] if os.environ.get('LOG_FILE') else [])
)

class TwitterBot:
    def __init__(self):
        self.oauth = None
        self.setup_oauth()
        self.posted_tweets = set()  # Track posted content to avoid duplicates
        
    def setup_oauth(self):
        """Setup Twitter OAuth session"""
        logging.info("➡️ Setting up Twitter OAuth")
        consumer_key = os.environ.get("TWITTER_API_KEY")
        consumer_secret = os.environ.get("TWITTER_API_SECRET")
        access_token = os.environ.get("TWITTER_ACCESS_TOKEN")
        access_token_secret = os.environ.get("TWITTER_ACCESS_SECRET")

        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            logging.error("❌ Missing Twitter API credentials as environment variables.")
            return

        self.oauth = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret,
        )
        
    def clean_tweet_text(self, text):
        """Clean and format tweet text"""
        text = re.sub(r'^(Here\'s|Here is|Tweet:|Thought:|Here\'s a thought:|Quick thought:|Check out this insight:|Here is your tweet:|Here\'s a tweet for you:)', '', text, flags=re.IGNORECASE).strip()
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        text = text.strip('"\' \n')
        
        if '#' not in text and random.random() < 0.3:
            hashtags = ['#DataScience', '#Analytics', '#MachineLearning', '#BigData', '#Python', '#SQL', '#TechTips', '#AI', '#DeepLearning', '#DataAnalytics']
            text += f" {random.choice(hashtags)}"
            
        if len(text) > 280:
            text = text[:277] + "..."
            last_space = text.rfind(' ')
            if last_space > 200:
                text = text[:last_space] + "..."

        return text

    def generate_tweet_with_groq(self, topic):
        """Generate tweet using Groq API"""
        groq_api_key = os.environ.get("GROQ_API_KEY")
        if not groq_api_key:
            logging.error("❌ Groq API key not found in environment (GROQ_API_KEY).")
            return None

        api_url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }

        tweet_styles_str = os.environ.get('TWEET_STYLES')
        tweet_styles = json.loads(tweet_styles_str) if tweet_styles_str else [
            "Share a practical tip about {topic} that beginners can apply immediately.",
            "What's the most common mistake people make with {topic}? Share the solution.",
            "Explain {topic} in one sentence that a 5-year-old could understand.",
            "Hot take: {topic} is overrated/underrated because...",
            "If you could only know one thing about {topic}, it should be this:",
            "Quick reminder: {topic} doesn't have to be complicated. Here's how:",
            "Unpopular opinion about {topic}:",
            "The best free resource for learning {topic} is...",
            "Real talk: {topic} changed how I think about data. Here's why:",
            "Tell me something surprising about {topic}.",
            "What's a common misconception about {topic}?",
            "How can {topic} be applied in everyday life?",
            "The future of {topic} is...",
            "If you're struggling with {topic}, try this simple approach:"
        ]

        selected_style = random.choice(tweet_styles).format(topic=topic)
        
        prompt = f"Write a concise Twitter post about {topic}. {selected_style} Requirements: Under 280 characters, engaging, professional tone. Don't include hashtags unless specifically relevant. Just return the tweet text, nothing else."

        payload = {
            "model": "gpt-oss-20b",  # ✅ updated model
            "messages": [
                {
                    "role": "system",
                    "content": "You are a data science expert who writes engaging, concise Twitter posts. Write only the tweet content, no additional text or explanations."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9
        }

        logging.info(f"🧠 Generating tweet for topic: {topic} using Groq API.")

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

        except requests.exceptions.HTTPError as e:
            logging.error(f"❌ Groq API request failed: {e}. Falling back to llama-3.3-70b.")
            payload["model"] = "llama-3.3-70b"  # ✅ fallback model
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Groq API network error: {e}")
            return self.generate_fallback_tweet(topic)

        if 'choices' in result and len(result['choices']) > 0:
            raw_tweet = result['choices'][0]['message']['content'].strip()
            tweet = self.clean_tweet_text(raw_tweet)
            
            if tweet in self.posted_tweets:
                logging.warning("⚠️ Duplicate tweet detected, regenerating...")
                return self.generate_fallback_tweet(topic)
            
            if len(tweet) <= 280 and len(tweet) > 10:
                logging.info(f"✅ Generated tweet ({len(tweet)} chars): {tweet}")
                return tweet
            else:
                logging.warning(f"⚠️ Tweet length issue ({len(tweet)} chars) or too short after cleaning. Using fallback.")
                return self.generate_fallback_tweet(topic)
        else:
            logging.error(f"❌ Unexpected Groq API response structure: {json.dumps(result)}")
            return self.generate_fallback_tweet(topic)

    def generate_fallback_tweet(self, topic):
        """Generate a simple fallback tweet when AI generation fails"""
        fallback_templates = [
            f"Today's focus: {topic}. What's your experience been like?",
            f"Quick question: What's the biggest challenge you face with {topic}?",
            f"Reminder: {topic} doesn't have to be overwhelming. Start small, build up.",
            f"Working on {topic} today. Any tips or resources you'd recommend?",
            f"The more I learn about {topic}, the more fascinating it becomes.",
            f"Just shared a thought on {topic}. What's your take?",
            f"Exploring {topic} today. Any interesting insights you've found?"
        ]
        
        tweet = random.choice(fallback_templates)
        tweet = self.clean_tweet_text(tweet)
        logging.info(f"🔄 Using fallback tweet: {tweet}")
        return tweet

    def post_tweet(self, tweet_text):
        """Post tweet to Twitter with better error handling"""
        if not self.oauth or not tweet_text:
            logging.error("❌ Cannot post tweet. Missing OAuth or tweet text.")
            return False

        payload = {"text": tweet_text}
        
        try:
            response = self.oauth.post("https://api.twitter.com/2/tweets", json=payload, timeout=30)
            
            if response.status_code == 201:
                tweet_id = response.json()['data']['id']
                self.posted_tweets.add(tweet_text)
                logging.info(f"✅ Tweet posted successfully! ID: {tweet_id}")
                logging.info(f"📝 Content: {tweet_text}")
                return True
            else:
                logging.error(f"❌ Twitter API error: {response.status_code}")
                logging.error(f"Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error posting tweet: {e}")
            return False
        except Exception as e:
            logging.error(f"❌ Unexpected error posting tweet: {e}")
            return False

    def generate_and_post(self, schedule_time):
        """Generate and post a tweet"""
        logging.info(f"➡️ Generating tweet for schedule: {schedule_time}")
        
        topics_str = os.environ.get('TOPICS')
        topics = json.loads(topics_str) if topics_str else [
            "Data Pipeline Architecture",
            "SQL Performance Optimization", 
            "Python Data Manipulation with Pandas",
            "Machine Learning Feature Engineering",
            "Data Visualization Best Practices",
            "ETL vs ELT Processes",
            "Database Indexing Strategies",
            "API Integration for Data Collection",
            "Data Quality Validation Techniques",
            "Cloud Data Warehousing Solutions",
            "Real-time Data Processing",
            "Data Science Project Organization",
            "Statistical Analysis in Business",
            "Data Storytelling Techniques",
            "Automated Reporting Systems",
            "Big Data Technologies (Spark, Hadoop)",
            "Data Governance and Ethics",
            "Time Series Analysis",
            "Natural Language Processing (NLP)",
            "Computer Vision Basics",
            "Deployment of Machine Learning Models"
        ]

        topic = random.choice(topics)
        tweet_text = self.generate_tweet_with_groq(topic)

        if tweet_text and self.post_tweet(tweet_text):
            return tweet_text
        else:
            logging.error(f"❌ Failed to generate or post tweet for {schedule_time}")
            return None

    def run_bot(self):
        """Main bot execution with improved scheduling"""
        logging.info("🚀 Starting Twitter bot...")
        
        if not self.oauth:
            logging.error("❌ Twitter authentication failed. Exiting.")
            return []

        posted_tweets = []
        
        if os.environ.get('POST_IMMEDIATELY', 'false').lower() == 'true':
            logging.info("🔹 Posting immediate tweet")
            tweet = self.generate_and_post("immediate")
            if tweet:
                posted_tweets.append(tweet)

        schedule_times_str = os.environ.get('SCHEDULE_TIMES', '["09:00", "14:00", "18:00"]')
        schedule_times = json.loads(schedule_times_str)
        
        for time_str in schedule_times:
            try:
                schedule.every().day.at(time_str).do(lambda t=time_str: self.generate_and_post(t))
                logging.info(f"⏰ Scheduled tweet for {time_str}")
            except schedule.InvalidTimeError:
                logging.error(f"❌ Invalid schedule time: {time_str}")

        duration_hours = float(os.environ.get('RUN_DURATION_HOURS', '24'))
        end_time = time.time() + (duration_hours * 60 * 60)
        
        logging.info(f"🕒 Bot will run for {duration_hours} hours")
        
        while time.time() < end_time and schedule.get_jobs():
            schedule.run_pending()
            time.sleep(60)

        logging.info("✅ Bot execution completed")
        return posted_tweets

def main():
    """Main entry point"""
    try:
        bot = TwitterBot()
        posted_tweets = bot.run_bot()
        logging.info(f"🎉 Session complete. Posted {len(posted_tweets)} tweets.")
        
        if posted_tweets:
            logging.info("📋 Posted tweets:")
            for i, tweet in enumerate(posted_tweets, 1):
                logging.info(f"{i}. {tweet}")
                
    except KeyboardInterrupt:
        logging.info("🛑 Bot stopped by user")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()
