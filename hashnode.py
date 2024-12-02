import os
import requests
import frontmatter
import logging
from constants import HASHNODE_API_KEY, HASHNODE_PUBLICATION_ID


class HashNodeBlogSync:
    def __init__(self, obsidian_folder, hashnode_personal_access_token, publication_id):
        """
        Initialize the Hashnode blog sync utility

        :param obsidian_folder: Path to the Obsidian folder containing blog drafts
        :param hashnode_personal_access_token: Your Hashnode Personal Access Token
        :param publication_id: Your Hashnode Publication ID
        """
        self.obsidian_folder = obsidian_folder
        self.hashnode_token = hashnode_personal_access_token
        self.publication_id = publication_id
        self.base_url = "https://gql.hashnode.com"

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)

    def _parse_markdown_file(self, filepath):
        """
        Parse Markdown file with frontmatter

        :param filepath: Path to the Markdown file
        :return: Parsed frontmatter and content
        """
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                post = frontmatter.load(file)

            # Extract required fields with default values
            return {
                "title": post.get("title", "Untitled"),
                "content": post.content.strip(),  # Ensure content is not None
                "canonicalUrl": post.get(
                    "canonical_url", ""
                ),  # Default to empty string
                "coverImageOptions": {
                    "coverImageURL": post.get("cover_image", "")
                },  # Default to empty string
                "existing_post_id": post.get(
                    "hashnode_post_id"
                ),  # Get existing post ID
            }
        except Exception as e:
            self.logger.error(f"Error parsing Markdown file {filepath}: {e}")
            raise

    def publish_to_hashnode(self, blog_data):
        """
        Publish or update blog post on Hashnode using the publishPost mutation.

        :param blog_data: Dictionary containing blog post details
        :param existing_post_id: Optional ID for updating an existing post (not needed for publishPost)
        :return: Published post ID
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.hashnode_token}",
        }

        # Determine if this is an update or a new post
        is_update = bool(blog_data.get("existing_post_id"))

        if is_update:
            # Mutation to update an existing post
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
            # Mutation to publish a new post
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

        # Add optional fields if present
        if blog_data.get("tags"):
            variables["input"]["tags"] = blog_data["tags"]
        if blog_data.get("canonical_url"):
            variables["input"]["canonicalUrl"] = blog_data["canonical_url"]
        if blog_data.get("cover_image"):
            variables["input"]["coverImage"] = blog_data["cover_image"]

        # Send the request
        response = requests.post(
            self.base_url,
            json={"query": query, "variables": variables},
            headers=headers,
        )
        try:
            response.raise_for_status()
            result = response.json()

            print("Full API Response:", result)

            # Extract post ID based on whether it's an update or new post
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
        # Iterate through all markdown files in the obsidian folder
        for filename in os.listdir(self.obsidian_folder):
            if filename.endswith(".md"):
                filepath = os.path.join(self.obsidian_folder, filename)
                try:
                    # Parse the blog file
                    blog_data = self._parse_markdown_file(filepath)

                    # Publish or update the post
                    post_id = self.publish_to_hashnode(blog_data)

                    # Update file with Hashnode post ID if it's a new post
                    with open(filepath, "r", encoding="utf-8") as file:
                        post = frontmatter.load(file)

                    # Only update if there's no existing post ID
                    if not post.get("hashnode_post_id"):
                        post["hashnode_post_id"] = post_id

                        with open(filepath, "wb") as file:
                            frontmatter.dump(post, file)

                except Exception as e:
                    self.logger.error(f"Error syncing {filepath}: {e}")


def main():
    # Configure these with your specific details
    OBSIDIAN_BLOG_FOLDER = "/home/ayroid/Documents/Learnings/Tech/SystemDesign"
    HASHNODE_TOKEN = HASHNODE_API_KEY
    PUBLICATION_ID = HASHNODE_PUBLICATION_ID

    sync_manager = HashNodeBlogSync(
        OBSIDIAN_BLOG_FOLDER, HASHNODE_TOKEN, PUBLICATION_ID
    )

    print(f"Starting Hashnode Blog Sync for {OBSIDIAN_BLOG_FOLDER}")
    sync_manager.sync_blog_files()
    print("Sync completed.")


if __name__ == "__main__":
    main()