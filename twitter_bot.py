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
        self.posted_tweets = set()
        # Available models to try (in order of preference)
        self.models = [
            "microsoft/DialoGPT-medium",
            "facebook/blenderbot-400M-distill",
            "gpt2-medium",
            "distilgpt2"
        ]
        
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
        text = re.sub(r'^(Here\'s|Here is|Sure,|Certainly)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        text = text.strip('"\' \n')
        
        # Remove model artifacts
        text = re.sub(r'<\|.*?\|>', '', text)  # Remove special tokens
        text = re.sub(r'^Tweet:\s*', '', text, flags=re.IGNORECASE)
        
        # Ensure proper hashtag formatting
        if '#' not in text and random.random() < 0.3:
            hashtags = ['#DataScience', '#Analytics', '#MachineLearning', '#BigData', '#Python', '#SQL']
            text += f" {random.choice(hashtags)}"
            
        return text.strip()

    def generate_tweet_with_huggingface(self, topic):
        """Generate tweet using Hugging Face models with fallback"""
        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HF")
        if not hf_token:
            logging.error("❌ Hugging Face API token not found.")
            return self.generate_fallback_tweet(topic)

        headers = {"Authorization": f"Bearer {hf_token}"}

        # Tweet prompts for better generation
        prompts = [
            f"Write a short professional tweet about {topic} for data professionals:",
            f"Share a quick tip about {topic} in under 280 characters:",
            f"What's important to know about {topic}?",
            f"Quick insight about {topic}:",
            f"Data professionals, here's why {topic} matters:"
        ]

        prompt = random.choice(prompts)
        
        # Try different models until one works
        for model_name in self.models:
            try:
                logging.info(f"🧠 Trying model: {model_name} for topic: {topic}")
                
                # Payload for text generation
                payload = {
                    "inputs": prompt,
                    "parameters": {
                        "max_new_tokens": 60,
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "do_sample": True,
                        "repetition_penalty": 1.2,
                        "return_full_text": False
                    }
                }

                model_url = f"https://api-inference.huggingface.co/models/{model_name}"
                response = requests.post(
                    model_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )

                if response.status_code == 503:
                    logging.warning(f"⚠️ Model {model_name} is loading, trying next...")
                    continue
                    
                response.raise_for_status()
                result = response.json()

                # Parse response based on model type
                tweet_text = self.extract_tweet_from_response(result, prompt)
                
                if tweet_text:
                    tweet_text = self.clean_tweet_text(tweet_text)
                    
                    # Validate tweet
                    if self.is_valid_tweet(tweet_text):
                        logging.info(f"✅ Generated tweet ({len(tweet_text)} chars): {tweet_text}")
                        return tweet_text
                    else:
                        logging.warning(f"⚠️ Invalid tweet from {model_name}, trying next model...")
                        continue
                        
            except requests.exceptions.RequestException as e:
                logging.warning(f"⚠️ Request failed for {model_name}: {e}")
                continue
            except Exception as e:
                logging.warning(f"⚠️ Error with {model_name}: {e}")
                continue

        # If all models fail, use fallback
        logging.warning("⚠️ All models failed, using fallback")
        return self.generate_fallback_tweet(topic)

    def extract_tweet_from_response(self, result, original_prompt):
        """Extract tweet text from different response formats"""
        try:
            if isinstance(result, list) and result:
                if 'generated_text' in result[0]:
                    raw_text = result[0]['generated_text']
                    # Remove the original prompt if it's included
                    if original_prompt in raw_text:
                        tweet = raw_text.split(original_prompt)[-1].strip()
                    else:
                        tweet = raw_text.strip()
                    return tweet
                elif 'text' in result[0]:
                    return result[0]['text'].strip()
            elif isinstance(result, dict):
                if 'generated_text' in result:
                    return result['generated_text'].strip()
                elif 'text' in result:
                    return result['text'].strip()
        except (KeyError, IndexError, TypeError):
            pass
        
        return None

    def is_valid_tweet(self, tweet):
        """Validate if the generated text is a good tweet"""
        if not tweet or len(tweet) < 10 or len(tweet) > 280:
            return False
        
        # Check for duplicates
        if tweet in self.posted_tweets:
            return False
            
        # Avoid common AI artifacts
        bad_patterns = [
            r'^(I|As an AI|Sorry|I cannot)',
            r'(\.{3,}|\[.*?\])',  # Multiple dots or brackets
            r'^(The|A|An)\s+\w+\s+(is|are|was|were)\s+',  # Too generic starts
        ]
        
        for pattern in bad_patterns:
            if re.search(pattern, tweet, re.IGNORECASE):
                return False
                
        return True

    def generate_fallback_tweet(self, topic):
        """Generate a simple fallback tweet when AI generation fails"""
        fallback_templates = [
            f"Today's focus: {topic}. What's your experience?",
            f"Quick question: What challenges do you face with {topic}?",
            f"Reminder: {topic} doesn't have to be overwhelming. Start small! 💪",
            f"Working on {topic} today. Any tips to share?",
            f"The more I learn about {topic}, the more interesting it gets! 🤔",
            f"Hot take: {topic} is underrated in the data world. Thoughts?",
            f"Pro tip: Master the basics of {topic} before moving to advanced concepts.",
            f"Anyone else think {topic} deserves more attention in data science?",
            f"Real talk: {topic} changed my approach to data work. What changed yours?",
            f"If you're learning {topic}, what's your biggest question right now?"
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
            "Python Data Manipulation",
            "Machine Learning Feature Engineering",
            "Data Visualization Best Practices",
            "ETL vs ELT Processes",
            "Database Indexing Strategies",
            "API Integration for Data Collection",
            "Data Quality Validation",
            "Cloud Data Warehousing",
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
