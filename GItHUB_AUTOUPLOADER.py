#!/usr/bin/env python3

import os
import sys
import json
import base64
import schedule
import time
import threading
from datetime import datetime
from pathlib import Path
import requests

class GitHubAutoUploader:
    def __init__(self):
        self.config_file = "github_uploader_config.json"
        self.github_token = None
        self.github_username = None
        self.scheduled_jobs = []
        self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.github_token = config.get('github_token')
                    self.github_username = config.get('github_username')
            except Exception as e:
                print(f"Oops! Couldn't load config: {e}")
    
    def save_config(self):
        config = {
            'github_token': self.github_token,
            'github_username': self.github_username
        }
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            print("✅ Configuration saved!")
        except Exception as e:
            print(f"Couldn't save config: {e}")
    
    def setup_github_credentials(self):
        print("\n🔑 Let's set up your GitHub credentials!")
        if not self.github_token:
            print("Head to https://github.com/settings/tokens and generate a token with 'repo' permissions.")
            self.github_token = input("Paste your token here: ").strip()
        
        if not self.github_username:
            self.github_username = input("Your GitHub username: ").strip()
        
        if self.test_github_connection():
            self.save_config()
            return True
        else:
            print("Something went wrong. Please try again.")
            self.github_token = None
            self.github_username = None
            return False
    
    def test_github_connection(self):
        try:
            headers = {'Authorization': f'token {self.github_token}'}
            r = requests.get('https://api.github.com/user', headers=headers)
            if r.status_code == 200:
                print(f"🎉 Hello, {r.json()['login']}! You're all set.")
                return True
            else:
                print(f"GitHub said: {r.status_code}")
                return False
        except Exception as e:
            print(f"Error testing connection: {e}")
            return False
    
    def create_github_repo(self, repo_name, description="Auto-created repository"):
        headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        data = {
            'name': repo_name,
            'description': description,
            'private': False,
            'auto_init': True
        }
        try:
            r = requests.post('https://api.github.com/user/repos', headers=headers, json=data)
            if r.status_code == 201:
                print(f"✅ Repo '{repo_name}' created!")
                return True
            elif r.status_code == 422:
                print(f"⚠️ Repo '{repo_name}' already exists.")
                return True
            else:
                print(f"Repo creation failed: {r.status_code} - {r.text}")
                return False
        except Exception as e:
            print(f"Error creating repo: {e}")
            return False
    
    def encode_file_content(self, path):
        try:
            with open(path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            print(f"Can't read {path}: {e}")
            return None

    def upload_single_file(self, repo_name, file_path, github_path=None):
        if not os.path.exists(file_path):
            print(f"Missing file: {file_path}")
            return False
        
        if os.path.isdir(file_path):
            return self.upload_directory(repo_name, file_path)

        content = self.encode_file_content(file_path)
        if not content:
            return False

        github_path = github_path or os.path.basename(file_path)
        url = f"https://api.github.com/repos/{self.github_username}/{repo_name}/contents/{github_path}"
        headers = {'Authorization': f'token {self.github_token}'}
        
        r = requests.get(url, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        action = "Updated" if sha else "Created"

        data = {
            'message': f'{action} {github_path} via auto-uploader',
            'content': content
        }
        if sha:
            data['sha'] = sha

        r = requests.put(url, headers=headers, json=data)
        if r.status_code in [200, 201]:
            print(f"{action}: {github_path}")
            return True
        else:
            print(f"Error uploading {github_path}: {r.status_code}")
            return False

    def upload_directory(self, repo_name, dir_path, github_dir=""):
        count = 0
        for root, _, files in os.walk(dir_path):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, dir_path)
                github_path = os.path.join(github_dir, rel_path).replace('\\', '/')
                if self.upload_single_file(repo_name, full_path, github_path):
                    count += 1
        print(f"Uploaded {count} file(s) from {dir_path}")
        return count > 0

    def upload_files_to_repo(self, repo_name, paths):
        count = 0
        for path in paths:
            if self.upload_single_file(repo_name, path):
                count += 1
        print(f"✅ Uploaded {count} file(s) to '{repo_name}'")
        return count > 0

    def schedule_upload(self, repo_name, paths, time_str, repeat=1):
        job_id = f"{repo_name}_{int(time.time())}"

        def job():
            print(f"\n[{datetime.now()}] Uploading to '{repo_name}'...")
            self.upload_files_to_repo(repo_name, paths)
            for j in self.scheduled_jobs:
                if j['id'] == job_id:
                    j['remaining'] -= 1
                    if j['remaining'] <= 0:
                        schedule.cancel_job(j['job'])
                        self.scheduled_jobs.remove(j)
                        print(f"✅ Done with scheduled uploads for {repo_name}")
                    break
        
        job_sched = schedule.every().day.at(time_str).do(job)
        self.scheduled_jobs.append({
            'id': job_id,
            'job': job_sched,
            'repo': repo_name,
            'time': time_str,
            'remaining': repeat,
            'files': paths
        })

        print(f"⏰ Scheduled upload at {time_str} ({repeat} times)")

    def show_scheduled_jobs(self):
        if not self.scheduled_jobs:
            print("No jobs scheduled.")
            return
        print("\n=== Scheduled Jobs ===")
        for i, job in enumerate(self.scheduled_jobs, 1):
            print(f"{i}. Repo: {job['repo']} | Time: {job['time']} | Remaining: {job['remaining']}")

    def get_file_paths(self):
        paths = []
        print("Enter file/folder paths (empty line to finish):")
        while True:
            path = input("Path: ").strip()
            if not path:
                break
            if os.path.exists(path):
                paths.append(path)
                print(f"✔️ Added: {path}")
            else:
                print(f"❌ Not found: {path}")
        return paths

    def get_upload_time(self):
        while True:
            t = input("Upload time (HH:MM, 24hr): ").strip()
            try:
                datetime.strptime(t, '%H:%M')
                return t
            except ValueError:
                print("⛔ Invalid time format!")

    def get_repeat_count(self):
        while True:
            count = input("Repeat how many times? (default 1): ").strip()
            if not count:
                return 1
            if count.isdigit() and int(count) > 0:
                return int(count)
            print("Please enter a valid number.")

    def create_repo_and_schedule(self):
        repo_name = input("New repo name: ").strip()
        if not repo_name:
            print("Repo name can't be empty!")
            return
        desc = input("Description (optional): ").strip() or "Auto-created repository"
        if self.create_github_repo(repo_name, desc):
            self.schedule_upload_interactive(repo_name)

    def schedule_existing_repo(self):
        repo_name = input("Existing repo name: ").strip()
        if repo_name:
            self.schedule_upload_interactive(repo_name)

    def schedule_upload_interactive(self, repo_name):
        print(f"Let's schedule uploads for '{repo_name}'")
        paths = self.get_file_paths()
        if not paths:
            print("No valid files provided.")
            return
        t = self.get_upload_time()
        repeat = self.get_repeat_count()
        self.schedule_upload(repo_name, paths, t, repeat)

    def immediate_upload(self):
        repo_name = input("Repo name: ").strip()
        if not repo_name:
            print("Can't proceed without repo name.")
            return
        paths = self.get_file_paths()
        if not paths:
            return
        print(f"Uploading now to '{repo_name}'...")
        self.upload_files_to_repo(repo_name, paths)

    def interactive_mode(self):
        print("=== GitHub Auto Uploader ===")
        print("Upload files. Schedule tasks. No Git needed. 🚀\n")
        
        while not self.github_token or not self.github_username:
            if not self.setup_github_credentials():
                sys.exit(1)

        while True:
            print("\n1. Create repo & schedule upload")
            print("2. Schedule upload to existing repo")
            print("3. Upload now")
            print("4. View scheduled jobs")
            print("5. Reconfigure GitHub credentials")
            print("6. Exit")

            choice = input("Choose an option (1-6): ").strip()
            if choice == '1':
                self.create_repo_and_schedule()
            elif choice == '2':
                self.schedule_existing_repo()
            elif choice == '3':
                self.immediate_upload()
            elif choice == '4':
                self.show_scheduled_jobs()
            elif choice == '5':
                self.github_token = None
                self.github_username = None
                self.setup_github_credentials()
            elif choice == '6':
                print("👋 Goodbye!")
                break
            else:
                print("Try again with a valid option.")

    def run_scheduler(self):
        def runner():
            while True:
                schedule.run_pending()
                time.sleep(1)

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        print("🔁 Background scheduler running...")

def main():
    app = GitHubAutoUploader()
    if not app.github_token or not app.github_username:
        if not app.setup_github_credentials():
            sys.exit(1)
    app.run_scheduler()
    app.interactive_mode()

if __name__ == "__main__":
    main()
