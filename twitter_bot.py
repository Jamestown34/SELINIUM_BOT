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
        # Remove common AI response patterns
        text = re.sub(r'^(Here\'s|Here is)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        text = text.strip('"\' \n')
        
        # Ensure proper hashtag formatting
        if '#' not in text and random.random() < 0.3:  # 30% chance to add relevant hashtag
            hashtags = ['#DataScience', '#Analytics', '#MachineLearning', '#BigData', '#Python', '#SQL']
            text += f" {random.choice(hashtags)}"
            
        return text

    def generate_tweet_with_huggingface(self, topic):
        """Generate tweet using Hugging Face DeepSeek model with better prompting"""
        hf_token = os.environ.get("HF")
        if not hf_token:
            logging.error("❌ Hugging Face API token not found in environment.")
            return None

        headers = {"Authorization": f"Bearer {hf_token}"}

        tweet_styles_str = os.environ.get('TWEET_STYLES')
        tweet_styles = json.loads(tweet_styles_str) if tweet_styles_str else [
            "Share a practical tip about {topic} that beginners can apply immediately.",
            "What's the most common mistake people make with {topic}? Share the solution.",
            "Explain {topic} in one sentence that a 5-year-old could understand.",
            "Hot take: {topic} is overrated/underrated because...",
            "If you could only know one thing about {topic}, it should be this:",
            "Thread: Why {topic} matters more than you think (1/3)",
            "Quick reminder: {topic} doesn't have to be complicated. Here's how:",
            "Unpopular opinion about {topic}:",
            "The best free resource for learning {topic} is...",
            "Real talk: {topic} changed how I think about data. Here's why:"
        ]

        selected_style = random.choice(tweet_styles).format(topic=topic)
        
        # Enhanced prompt for better tweet generation
        prompt = f"""Write a engaging Twitter post about: {selected_style}

Requirements:
- Under 280 characters
- Conversational and authentic tone
- No quotation marks around the response
- Include actionable insight or question
- Sound like a human data professional, not an AI

Tweet:"""

        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 80,
                "temperature": 0.8,
                "top_p": 0.9,
                "do_sample": True,
                "repetition_penalty": 1.1
            }
        }

        logging.info(f"🧠 Generating tweet for topic: {topic}")

        try:
            response = requests.post(
                ""https://api-inference.huggingface.co/models/deepseek-ai/DeepSeek-R1-0528",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            result = response.json()

            if isinstance(result, list) and result:
                raw_tweet = result[0]['generated_text']
                # Extract only the tweet part after "Tweet:"
                if "Tweet:" in raw_tweet:
                    tweet = raw_tweet.split("Tweet:")[-1].strip()
                else:
                    tweet = raw_tweet.strip()
                
                tweet = self.clean_tweet_text(tweet)
                
                # Check for duplicates
                if tweet in self.posted_tweets:
                    logging.warning("⚠️ Duplicate tweet detected, regenerating...")
                    return self.generate_fallback_tweet(topic)
                
                if len(tweet) <= 280 and len(tweet) > 10:  # Ensure reasonable length
                    logging.info(f"✅ Generated tweet ({len(tweet)} chars): {tweet}")
                    return tweet
                else:
                    logging.warning(f"⚠️ Tweet length issue ({len(tweet)} chars). Using fallback.")
                    return self.generate_fallback_tweet(topic)
            else:
                logging.error(f"❌ Unexpected Hugging Face response: {result}")
                return self.generate_fallback_tweet(topic)
                
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Hugging Face API request failed: {e}")
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
            f"The more I learn about {topic}, the more fascinating it becomes."
        ]
        
        tweet = random.choice(fallback_templates)
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
            "Automated Reporting Systems"
        ]

        topic = random.choice(topics)
        tweet_text = self.generate_tweet_with_huggingface(topic)

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
