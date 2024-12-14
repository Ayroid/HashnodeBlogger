import os
import requests
import frontmatter
import logging
from constants import HASHNODE_API_KEY, HASHNODE_PUBLICATION_ID, OBSIDIAN_BLOG_FOLDER


class HashNodeBlogSync:
    def __init__(
        self,
        obsidian_folder,
        hashnode_personal_access_token,
        publication_id,
    ):
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

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)

    def _parse_markdown_file(self, filepath):
        """
        Parse Markdown file with frontmatter and extract local image paths
        """
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                post = frontmatter.load(file)

            blog_data = {
                "title": post.get("title", "Untitled"),
                "content": post.content.strip(),
                "canonicalUrl": post.get("canonical_url", ""),
                "coverImageOptions": {"coverImageURL": post.get("cover_image", "")},
                "existing_post_id": post.get("hashnode_post_id"),
                "tags": [{"name": tag, "slug": tag} for tag in post.get("tags", [])],
            }

            return blog_data
        except Exception as e:
            self.logger.error(f"Error parsing Markdown file {filepath}: {e}")
            raise

    def publish_to_hashnode(self, blog_data):
        """
        Publish or update blog post on Hashnode using the publishPost mutation.
        """

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.hashnode_token}",
        }

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

                    with open(filepath, "r", encoding="utf-8") as file:
                        post = frontmatter.load(file)

                    if not post.get("hashnode_post_id"):
                        post["hashnode_post_id"] = post_id

                        with open(filepath, "wb") as file:
                            frontmatter.dump(post, file)

                except Exception as e:
                    self.logger.error(f"Error syncing {filepath}: {e}")


def main():

    sync_manager = HashNodeBlogSync(
        OBSIDIAN_BLOG_FOLDER,
        HASHNODE_API_KEY,
        HASHNODE_PUBLICATION_ID,
    )

    print(f"Starting Hashnode Blog Sync for {OBSIDIAN_BLOG_FOLDER}")
    sync_manager.sync_blog_files()
    print("Sync completed.")


if __name__ == "__main__":
    main()
