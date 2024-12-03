import os
import requests
import frontmatter
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from constants import (
    HASHNODE_API_KEY,
    HASHNODE_PUBLICATION_ID,
    GOOGLE_DRIVE_CREDENTIALS_PATH,
)


class HashNodeBlogSync:
    def __init__(
        self,
        obsidian_folder,
        obsidian_images_folder,
        hashnode_personal_access_token,
        publication_id,
        drive_credentials_path,
    ):
        """
        Initialize the Hashnode blog sync utility

        :param obsidian_folder: Path to the Obsidian folder containing blog drafts
        :param hashnode_personal_access_token: Your Hashnode Personal Access Token
        :param publication_id: Your Hashnode Publication ID
        :param drive_credentials_path: Path to the Google Drive API credentials file
        """
        self.obsidian_folder = obsidian_folder
        self.obsidian_images_folder = obsidian_images_folder
        self.hashnode_token = hashnode_personal_access_token
        self.publication_id = publication_id
        self.base_url = "https://gql.hashnode.com"
        self.drive_credentials_path = drive_credentials_path
        self.drive_service = self._setup_drive_service()
        self.drive_folder_id = self._get_or_create_drive_folder("Hashnode Blog Images")

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)

    def _setup_drive_service(self):
        """
        Set up the Google Drive API service
        """
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        flow = InstalledAppFlow.from_client_secrets_file(
            self.drive_credentials_path, SCOPES
        )
        credentials = flow.run_local_server(port=0)
        return build("drive", "v3", credentials=credentials)

    def _get_or_create_drive_folder(self, folder_name):
        """
        Get the ID of the specified Google Drive folder, or create it if it doesn't exist
        """
        results = (
            self.drive_service.files()
            .list(
                q=f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}'",
                spaces="drive",
            )
            .execute()
        )
        folders = results.get("files", [])
        if folders:
            return folders[0]["id"]
        else:
            file_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            file = (
                self.drive_service.files()
                .create(body=file_metadata, fields="id")
                .execute()
            )
            return file.get("id")

    def _parse_markdown_file(self, filepath):
        """
        Parse Markdown file with frontmatter and extract local image paths
        """
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                post = frontmatter.load(file)

            # Extract required fields with default values
            blog_data = {
                "title": post.get("title", "Untitled"),
                "content": post.content.strip(),
                "canonicalUrl": post.get("canonical_url", ""),
                "coverImageOptions": {"coverImageURL": post.get("cover_image", "")},
                "existing_post_id": post.get("hashnode_post_id"),
                "tags": [{"name": tag, "slug": tag} for tag in post.get("tags", [])],
                "local_image_paths": self._extract_local_image_paths(post.content),
            }

            return blog_data
        except Exception as e:
            self.logger.error(f"Error parsing Markdown file {filepath}: {e}")
            raise

    def _extract_local_image_paths(self, content):
        """
        Extract local image paths from the content
        """
        local_image_paths = []
        for line in content.split("\n"):
            if line.startswith("![["):
                image_path = line.split("[[")[1].split("]]")[0]
                local_image_paths.append(
                    os.path.join(self.obsidian_images_folder, image_path)
                )
        return local_image_paths

    def _upload_images_to_drive(self, local_image_paths):
        """
        Upload local images to Google Drive and return public URLs
        """
        public_image_urls = []
        for local_path in local_image_paths:
            filename = os.path.basename(local_path)
            file_metadata = {"name": filename, "parents": [self.drive_folder_id]}
            media = (
                self.drive_service.files()
                .create(
                    body=file_metadata, media_body=local_path, fields="id, webViewLink"
                )
                .execute()
            )
            # Make the file publicly accessible
            permission = {
                "type": "anyone",
                "role": "reader",
            }
            self.drive_service.permissions().create(
                fileId=media.get("id"), body=permission
            ).execute()
            public_image_urls.append(media.get("webViewLink"))
        return public_image_urls

    def _replace_local_image_links(self, content, public_image_urls):
        """
        Replace local image links with public Google Drive URLs
        """
        for i, local_path in enumerate(self._extract_local_image_paths(content)):
            filename = os.path.basename(local_path)
            content = content.replace(
                f"![[{filename}]]", f"![Alt Text]({public_image_urls[i]})"
            )
        return content

    def publish_to_hashnode(self, blog_data):
        """
        Publish or update blog post on Hashnode using the publishPost mutation.
        """
        # Modify the content to replace local image links
        public_image_urls = self._upload_images_to_drive(blog_data["local_image_paths"])

        print("public_image_urls", public_image_urls)

        blog_data["content"] = self._replace_local_image_links(
            blog_data["content"], public_image_urls
        )

        # Proceed with publishing the post
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.hashnode_token}",
        }

        # Determine if this is an update or a new post
        is_update = bool(blog_data.get("existing_post_id"))

        if is_update:
            query = """
            mutation UpdatePost($input: UpdatePostInput!) {
                updatePost(input: $input) {
                    post {
                        id
                        title
                        url
                    }
                }
            }
            """
            variables = {
                "input": {
                    "id": blog_data["existing_post_id"],
                    "title": blog_data["title"],
                    "contentMarkdown": blog_data["content"],
                }
            }
        else:
            query = """
            mutation PublishPost($input: PublishPostInput!) {
                publishPost(input: $input) {
                    post {
                        id
                        title
                        url
                    }
                }
            }
            """
            variables = {
                "input": {
                    "title": blog_data["title"],
                    "publicationId": self.publication_id,
                    "contentMarkdown": blog_data["content"],
                }
            }

        if blog_data.get("tags"):
            variables["input"]["tags"] = blog_data["tags"]
        if blog_data.get("canonical_url"):
            variables["input"]["canonicalUrl"] = blog_data["canonical_url"]
        if blog_data.get("cover_image"):
            variables["input"]["coverImage"] = blog_data["cover_image"]

        response = requests.post(
            self.base_url,
            json={"query": query, "variables": variables},
            headers=headers,
        )
        try:
            response.raise_for_status()
            result = response.json()

            if is_update:
                post_id = result["data"]["updatePost"]["post"]["id"]
                action = "updated"
                url = result["data"]["updatePost"]["post"]["url"]
            else:
                post_id = result["data"]["publishPost"]["post"]["id"]
                action = "published"
                url = result["data"]["publishPost"]["post"]["url"]

            self.logger.info(
                f"Blog post {action}: {blog_data['title']} ({post_id}) at {url}"
            )

            return post_id
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP Error: {response.text}")
            raise

    def sync_blog_files(self):
        """
        Sync all Markdown files in the Obsidian folder to Hashnode
        """
        for filename in os.listdir(self.obsidian_folder):
            if filename.endswith(".md"):
                filepath = os.path.join(self.obsidian_folder, filename)
                try:
                    blog_data = self._parse_markdown_file(filepath)
                    post_id = self.publish_to_hashnode(blog_data)

                    # Update file with Hashnode post ID if it's a new post
                    with open(filepath, "r", encoding="utf-8") as file:
                        post = frontmatter.load(file)

                    if not post.get("hashnode_post_id"):
                        post["hashnode_post_id"] = post_id

                        with open(filepath, "wb") as file:
                            frontmatter.dump(post, file)

                except Exception as e:
                    self.logger.error(f"Error syncing {filepath}: {e}")


def main():
    OBSIDIAN_BLOG_FOLDER = "/home/ayroid/Documents/Learnings/Tech/SystemDesign"
    OBSIDIAN_IMAGES_FOLDER = "/home/ayroid/Documents/Learnings"
    HASHNODE_TOKEN = HASHNODE_API_KEY
    PUBLICATION_ID = HASHNODE_PUBLICATION_ID
    DRIVE_CREDENTIALS_PATH = GOOGLE_DRIVE_CREDENTIALS_PATH

    sync_manager = HashNodeBlogSync(
        OBSIDIAN_BLOG_FOLDER,
        OBSIDIAN_IMAGES_FOLDER,
        HASHNODE_TOKEN,
        PUBLICATION_ID,
        DRIVE_CREDENTIALS_PATH,
    )

    print(f"Starting Hashnode Blog Sync for {OBSIDIAN_BLOG_FOLDER}")
    sync_manager.sync_blog_files()
    print("Sync completed.")


if __name__ == "__main__":
    main()
