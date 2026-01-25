import Image from 'next/image';

export default function AboutPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <div className="flex flex-col sm:flex-row items-center sm:items-start gap-6 mb-10">
        <Image
          src="/images/professional_face.jpeg"
          alt="Brian Ellis"
          width={160}
          height={160}
          className="rounded-full object-cover w-40 h-40 shadow-lg"
        />
        <div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Brian Ellis</h1>
          <p className="text-gray-600 mb-4">AI/ML Engineer &bull; Composer &bull; Veteran</p>
          <div className="flex gap-4">
            <a
              href="https://github.com/brianellis1997"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-600 hover:text-sky-700 transition-colors"
            >
              GitHub
            </a>
            <a
              href="https://linkedin.com/in/BEllis1997"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-600 hover:text-sky-700 transition-colors"
            >
              LinkedIn
            </a>
            <a
              href="https://www.youtube.com/@FastGoing247"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-600 hover:text-sky-700 transition-colors"
            >
              YouTube
            </a>
          </div>
        </div>
      </div>

      <div className="prose">
        <p className="text-lg text-gray-700 leading-relaxed">
          I&apos;m a Machine Learning Engineer with over 6 years of experience designing, developing,
          and deploying ML models across defense and enterprise environments. Currently building
          production LLM-based agentic systems, RAG pipelines, and fine-tuned transformer models
          for DoD customers.
        </p>

        <h2>Military Service</h2>
        <div className="flex flex-col sm:flex-row gap-6 items-start not-prose mb-6">
          <Image
            src="/images/military.jpeg"
            alt="Brian Ellis in military service"
            width={200}
            height={200}
            className="rounded-lg object-cover shadow-md"
          />
          <p className="text-gray-700 leading-relaxed">
            I served six years in the <strong>United States Air Force</strong> as a Cyber Defense Analyst
            and Machine Learning Engineer. During my service, I designed anomaly detection systems using
            autoencoders, developed logistic regression classifiers for predictive equipment maintenance,
            and implemented reinforcement learning algorithms for RF network optimization. I hold an
            active U.S. Secret Clearance.
          </p>
        </div>

        <h2>Music &amp; Composition</h2>
        <div className="flex flex-col sm:flex-row gap-6 items-start not-prose mb-6">
          <Image
            src="/images/piano.jpeg"
            alt="Brian Ellis at the piano"
            width={200}
            height={200}
            className="rounded-lg object-cover shadow-md"
          />
          <div className="text-gray-700 leading-relaxed">
            <p className="mb-3">
              Before diving into data science, I studied <strong>music composition at Penn State</strong>.
              I&apos;m a classically trained pianist and composer, with Bach and Chopin being my greatest
              inspirations. Music remains a core part of my life—I still compose and perform regularly.
            </p>
            <p>
              Check out my compositions on{' '}
              <a
                href="https://www.youtube.com/@FastGoing247"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-600 hover:text-sky-700"
              >
                YouTube
              </a>.
            </p>
          </div>
        </div>

        <h2>What This Blog Covers</h2>
        <p>
          Here you&apos;ll find deep dives into machine learning, AI developments, LLM applications,
          and explorations of emerging technologies. Some posts are AI-assisted using tools I&apos;ve
          built—combining automated research with human curation to create well-researched,
          long-form content.
        </p>

        <h2>Technical Background</h2>
        <p>
          <strong>Languages:</strong> Python, SQL, Bash, R<br />
          <strong>ML Frameworks:</strong> PyTorch, TensorFlow, scikit-learn, XGBoost, Hugging Face Transformers<br />
          <strong>LLM &amp; RAG:</strong> LangChain, LangGraph, Llamaindex, Ollama, LoRA fine-tuning, RLHF<br />
          <strong>Infrastructure:</strong> MLflow, Docker, CI/CD, SageMaker, AWS, Lambda, Git
        </p>
      </div>

      <div className="mt-12 pt-8 border-t border-gray-200">
        <div className="flex items-center gap-4">
          <Image
            src="/images/smile_face.jpeg"
            alt="Brian Ellis"
            width={64}
            height={64}
            className="rounded-full object-cover w-16 h-16"
          />
          <p className="text-gray-600">
            Thanks for stopping by! Feel free to reach out on{' '}
            <a
              href="https://linkedin.com/in/BEllis1997"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-600 hover:text-sky-700"
            >
              LinkedIn
            </a>{' '}
            if you&apos;d like to connect.
          </p>
        </div>
      </div>
    </div>
  );
}
