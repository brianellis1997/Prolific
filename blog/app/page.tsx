import { getAllPosts } from '@/lib/posts';
import { PostCard } from '@/components/PostCard';

export default function Home() {
  const posts = getAllPosts();

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Posts</h1>
      <p className="text-gray-500 mb-8">Thoughts, ideas, and explorations.</p>

      {posts.length === 0 ? (
        <p className="text-gray-400 py-8">No posts yet. Add markdown files to content/posts/</p>
      ) : (
        <div>
          {posts.map((post) => (
            <PostCard key={post.slug} post={post} />
          ))}
        </div>
      )}
    </div>
  );
}
