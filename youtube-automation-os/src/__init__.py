"""YouTube Automation OS core library.

Skill scripts under ``skills/*/scripts`` are thin command-line wrappers around this
package. Everything that talks to Google goes through ``youtube_client.YouTubeClient``,
which applies quota accounting, bounded retries and structured logging.
"""

__version__ = "1.0.0"
