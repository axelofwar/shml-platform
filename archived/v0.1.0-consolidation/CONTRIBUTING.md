# Contributing to Ray Compute Platform

## Development Setup

### Prerequisites
- Docker & Docker Compose
- Node.js 20+
- Python 3.11+
- Git

### Getting Started

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/ray-compute.git
   cd ray-compute
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Install dependencies**
   ```bash
   # Web UI
   cd web_ui
   npm install
   
   # API
   cd ../api
   pip install -r requirements.txt
   ```

4. **Start development servers**
   ```bash
   # Web UI (with hot reload)
   cd web_ui
   npm run dev
   
   # API
   cd api
   uvicorn main:app --reload
   ```

## Code Style

### TypeScript/React
- Use TypeScript for all new code
- Follow Next.js App Router conventions
- Use functional components with hooks
- Prefer `const` over `let`
- Use meaningful variable names

### Python
- Follow PEP 8
- Use type hints
- Document functions with docstrings
- Use async/await for I/O operations

### CSS/Styling
- Use Tailwind CSS utility classes
- Follow shadcn/ui component patterns
- Avoid inline styles
- Use CSS variables for theming

## Git Workflow

### Branching Strategy
- `main` - Production-ready code
- `develop` - Integration branch
- `feature/*` - New features
- `bugfix/*` - Bug fixes
- `hotfix/*` - Urgent production fixes

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add user dashboard
fix: resolve OAuth redirect loop
docs: update setup guide
test: add authentication tests
chore: update dependencies
```

### Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes**
   - Write tests for new functionality
   - Update documentation
   - Run linters and tests locally

3. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

4. **Push to GitHub**
   ```bash
   git push origin feature/my-feature
   ```

5. **Create Pull Request**
   - Fill out PR template
   - Link related issues
   - Request reviews
   - Ensure CI passes

## Testing

### Unit Tests
```bash
# Web UI
cd web_ui
npm test

# API
cd api
pytest
```

### Integration Tests
```bash
npm run test:integration
```

### E2E Tests
```bash
npm run test:e2e
```

### Coverage
```bash
npm run test:ci  # Generates coverage report
```

## Common Issues & Solutions

### OAuth Circular Redirects
- Check `NEXTAUTH_URL` matches public URL
- Verify Authentik redirect URI configuration
- Ensure `issuer` and `jwks_endpoint` are set

### Styles Not Loading
- Verify `postcss.config.js` exists
- Check `tailwindcss-animate` is installed
- Rebuild Docker image: `docker-compose build --no-cache`

### Hydration Mismatches
- Don't access browser APIs during SSR
- Use mounting guard pattern
- Return consistent DOM structure

### Docker Networking
- Use service names for container-to-container communication
- Use public IPs/domains for browser access
- Check containers are on same network

## Code Review Guidelines

### For Reviewers
- ✅ Code follows style guidelines
- ✅ Tests are included and passing
- ✅ Documentation is updated
- ✅ No security vulnerabilities
- ✅ Performance considerations
- ✅ Accessibility standards met

### For Authors
- Respond to feedback promptly
- Make requested changes
- Keep PR scope focused
- Update PR description if scope changes

## Release Process

1. **Version bump**
   ```bash
   npm version patch|minor|major
   ```

2. **Update CHANGELOG.md**
   - List all changes since last release
   - Categorize: Added, Changed, Fixed, Removed

3. **Create release tag**
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```

4. **Deploy to production**
   - CI/CD pipeline automatically deploys tags
   - Monitor deployment status
   - Verify in production

## Documentation

### When to Update Docs
- Adding new features
- Changing APIs
- Fixing bugs that affect usage
- Adding configuration options

### Where to Update
- `README.md` - Overview and quick start
- `docs/OAUTH_SETUP_GUIDE.md` - Auth setup
- `LESSONS_LEARNED.md` - Debugging insights
- Code comments - Complex logic
- API documentation - Endpoint changes

## Performance Guidelines

### Web UI
- Use React.memo for expensive components
- Lazy load routes and components
- Optimize images (use next/image)
- Minimize bundle size
- Use server components when possible

### API
- Use async/await for I/O
- Cache frequently accessed data
- Index database queries
- Use connection pooling
- Monitor query performance

## Security Best Practices

### Authentication
- Never store tokens in localStorage
- Use HTTP-only cookies
- Validate JWTs on every request
- Implement rate limiting
- Use HTTPS in production

### Environment Variables
- Never commit secrets
- Use `.env.example` for documentation
- Rotate secrets regularly
- Use secret management in production

### Dependencies
- Regular security audits: `npm audit`
- Keep dependencies updated
- Review dependency licenses
- Use lock files

## Getting Help

- **Documentation**: Check `/docs` folder
- **Issues**: Search existing issues first
- **Discussions**: Use GitHub Discussions for questions
- **Slack/Discord**: Join our community (link)

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Questions?

Feel free to reach out:
- Create an issue
- Join our Discord
- Email: dev@ray-compute.example.com
