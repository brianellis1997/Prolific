import Link from 'next/link';
import type { PostMeta } from '@/lib/posts';

interface PostCardProps {
  post: PostMeta;
}

export function PostCard({ post }: PostCardProps) {
  const formattedDate = post.date
    ? new Date(post.date).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '';

  return (
    <article className="py-8 border-b border-gray-100 last:border-0">
      <Link href={`/posts/${post.slug}`} className="group block">
        <h2 className="text-xl font-semibold text-gray-900 group-hover:text-sky-600 transition-colors mb-2">
          {post.title}
        </h2>
        {formattedDate && (
          <time className="text-sm text-gray-400 mb-3 block">{formattedDate}</time>
        )}
        {post.excerpt && (
          <p className="text-gray-600 leading-relaxed">{post.excerpt}</p>
        )}
      </Link>
    </article>
  );
}
