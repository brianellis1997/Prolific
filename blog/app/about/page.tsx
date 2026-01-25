export default function AboutPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-6">About</h1>
      <div className="prose">
        <h2>Hi, I'm Brian Ellis</h2>
        <p>
          I'm a software engineer passionate about technology, artificial intelligence,
          and building tools that make complex tasks simpler. This blog is where I
          explore ideas at the intersection of AI and practical applications.
        </p>

        <h2>What This Blog Covers</h2>
        <p>
          Here you'll find deep dives into machine learning, AI developments, software
          engineering insights, and explorations of emerging technologies. I aim to make
          complex topics accessible and share what I'm learning along the way.
        </p>
        <p>
          Some posts are AI-assisted using tools I've built, combining research
          capabilities with human curation to create well-researched, long-form content.
        </p>

        <h2>Get in Touch</h2>
        <p>
          Have questions or want to connect? Find me on{' '}
          <a href="https://github.com/brianellis1997" target="_blank" rel="noopener noreferrer">
            GitHub
          </a>.
        </p>
      </div>
    </div>
  );
}
