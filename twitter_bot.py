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
        # Remove common AI response patterns that might appear at the start
        text = re.sub(r'^(Here\'s|Here is|Tweet:|Thought:|Here\'s a thought:|Quick thought:|Check out this insight:|Here is your tweet:|Here\'s a tweet for you:)', '', text, flags=re.IGNORECASE).strip()
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        text = text.strip('"\' \n')
        
        # Ensure proper hashtag formatting - add one if missing for 30% of tweets
        if '#' not in text and random.random() < 0.3:
            hashtags = ['#DataScience', '#Analytics', '#MachineLearning', '#BigData', '#Python', '#SQL', '#TechTips', '#AI', '#DeepLearning', '#DataAnalytics']
            text += f" {random.choice(hashtags)}"
            
        # Ensure tweet is within Twitter's character limit (280 characters)
        if len(text) > 280:
            text = text[:277] + "..." # Truncate and add ellipsis, keeping space for 3 dots
            last_space = text.rfind(' ')
            if last_space > 200: # Only trim at word boundary if it's not too early
                text = text[:last_space] + "..."

        return text

    def generate_tweet_with_hugging_face(self, topic):
        """Generate tweet using Hugging Face API"""
        hugging_face_api_key = os.environ.get("HF")
        if not hugging_face_api_key:
            logging.error("❌ Hugging Face API key not found in environment (HF).")
            return None

        # Using a text generation model that's good for creating natural text
        api_url = "https://api-inference.huggingface.co/models/distilgpt2"
        headers = {
            "Authorization": f"Bearer {hugging_face_api_key}",
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
        
        # Create a prompt for Hugging Face text generation
        prompt = f"Write a Twitter post about {topic}. {selected_style} Keep it under 280 characters and engaging:"

        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 100,
                "temperature": 0.7,
                "top_p": 0.9,
                "do_sample": True,
                "return_full_text": False
            }
        }

        logging.info(f"🧠 Generating tweet for topic: {topic} using Hugging Face API.")

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            if isinstance(result, list) and len(result) > 0 and 'generated_text' in result[0]:
                raw_tweet = result[0]['generated_text'].strip()
                
                tweet = self.clean_tweet_text(raw_tweet)
                
                # Check for duplicates and reasonable length after cleaning
                if tweet in self.posted_tweets:
                    logging.warning("⚠️ Duplicate tweet detected, regenerating...")
                    return self.generate_fallback_tweet(topic)
                
                if len(tweet) <= 280 and len(tweet) > 10:  # Ensure reasonable length
                    logging.info(f"✅ Generated tweet ({len(tweet)} chars): {tweet}")
                    return tweet
                else:
                    logging.warning(f"⚠️ Tweet length issue ({len(tweet)} chars) or too short after cleaning. Using fallback.")
                    logging.warning(f"Problematic raw tweet: '{raw_tweet}'")
                    logging.warning(f"Problematic cleaned tweet: '{tweet}'")
                    return self.generate_fallback_tweet(topic)
            else:
                logging.error(f"❌ Unexpected Hugging Face API response structure: {json.dumps(result)}")
                return self.generate_fallback_tweet(topic)
                
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Hugging Face API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response status: {e.response.status_code}")
                logging.error(f"Response content: {e.response.text}")
            return self.generate_fallback_tweet(topic)
        except Exception as e:
            logging.error(f"❌ Unexpected error in tweet generation: {e}")
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
        # Ensure fallback tweet also goes through cleaning to add hashtags if desired
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
                self.posted_tweets.add(tweet_text)  # Track posted tweet
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
        # Generate tweet using Hugging Face
        tweet_text = self.generate_tweet_with_hugging_face(topic)

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
        
        # Post immediately if requested
        if os.environ.get('POST_IMMEDIATELY', 'false').lower() == 'true':
            logging.info("🔹 Posting immediate tweet")
            tweet = self.generate_and_post("immediate")
            if tweet:
                posted_tweets.append(tweet)

        # Setup scheduled posts
        schedule_times_str = os.environ.get('SCHEDULE_TIMES', '["09:00", "14:00", "18:00"]')
        schedule_times = json.loads(schedule_times_str)
        
        for time_str in schedule_times:
            try:
                schedule.every().day.at(time_str).do(lambda t=time_str: self.generate_and_post(t))
                logging.info(f"⏰ Scheduled tweet for {time_str}")
            except schedule.InvalidTimeError:
                logging.error(f"❌ Invalid schedule time: {time_str}")

        # Run scheduler
        duration_hours = float(os.environ.get('RUN_DURATION_HOURS', '24'))
        end_time = time.time() + (duration_hours * 60 * 60)
        
        logging.info(f"🕒 Bot will run for {duration_hours} hours")
        
        while time.time() < end_time and schedule.get_jobs():
            schedule.run_pending()
            time.sleep(60)  # Check every minute instead of every second

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
