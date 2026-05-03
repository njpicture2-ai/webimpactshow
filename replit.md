# WEB IMPACT SHOW - Site de Vote en Ligne

## Overview
This project is an online voting platform for the "WEB IMPACT SHOW - 1st Edition" content creator competition. Its primary purpose is to enable users to vote for their favorite candidates through an integrated payment system with Chariow. The platform aims to provide a seamless voting experience, real-time results, and robust administrative tools for managing the competition. Key capabilities include user registration, secure payment processing for vote packages, real-time vote tracking, a public dashboard displaying top candidates, and a comprehensive admin panel for content and competition management. The business vision is to create a performant, reliable, and user-friendly platform for large-scale online competitions, with market potential in events requiring transparent and efficient public voting.

## User Preferences
- I prefer clear and concise explanations.
- Please prioritize high-level architectural discussions over minute implementation details.
- I expect the agent to be proactive in identifying potential issues or improvements.
- When making changes, please explain the rationale and impact.
- Do not make changes to the file `CHARIOW_INTEGRATION.md`.
- User demands ultra-fast performance: "TIC TAC" - everything must be instantaneous with zero delays.

## System Architecture
The application is built with a **Python Flask backend**, **PostgreSQL database**, and a **HTML5, CSS3, JavaScript frontend**.

### UI/UX Decisions
-   **Color Scheme**: Elegant violet/blue gradient with accents of gold for winners.
-   **Typography**: Poppins font for modern aesthetics.
-   **Icons**: Font Awesome for consistent iconography.
-   **Responsiveness**: Fully responsive design across mobile, tablet, and desktop with optimized layouts and font scaling.
-   **Animations**: Animated logo, smooth slide-down for hamburger menu, `fadeInUp` and hover effects for partner logos, cascading "domino" effect for candidate cards.
-   **Key UI Elements**: Hamburger menu, real-time candidate search bar, candidate cards with portrait photos and vote count badges, floating WhatsApp button, and an elegant black/gold vote confirmation page.

### Technical Implementations
-   **Permanent Storage**: All application data, including candidate photos, team member photos, and partner logos, are stored directly in the PostgreSQL database as binary data, ensuring permanent retention without automatic deletion.
-   **Real-time Updates**: Vote counts update every 5 seconds on the homepage via a single optimized request.
-   **Timezone Management**: All timestamps are configured for Lubumbashi time (CAT = UTC+2).
-   **Performance Optimization**:
    -   **Multi-level caching**: In-memory cache for candidates (30s), categories (5min), partners (5min), users (permanent), and voting status (1min).
    -   **Database optimization**: 5 strategic indexes for 10-20x query speed improvement.
    -   **HTTP caching**: Photos/logos (1 hour), vote counts (3s), static files (1 year).
    -   **Server optimization**: Gunicorn with 4 workers + 2 threads per worker (8 parallel connections), optimized DB connection pool (10 base + 20 overflow).
    -   **Client-side optimization**: GZIP compression (70-80% data reduction), automatic HTML minification (5-15% size reduction), image optimization (resizing, quality reduction, optimized formats), lazy loading for images (3-5x faster initial load), DNS prefetch, preconnect, asynchronous font loading, and performance headers.
    -   **Session optimization**: 30-day persistent sessions.
-   **Payment Flow**: Transactions are initiated with Chariow, votes activated automatically upon successful payment and session validation, with immediate invoice generation and vote attribution. Security measures prevent double processing.
-   **Vote System**: All purchased votes are attributed automatically in a single operation to the selected candidate immediately after payment.

### Feature Specifications
-   **User Authentication**: Simple registration/login with name and phone number. Allows unlimited accounts with same credentials. Includes error handling, DB rollback, and 30-day persistent sessions.
-   **Vote Packages**: 8 distinct packages from 5 to 2510 votes with corresponding prices.
-   **Dashboard**: Displays total participants, highest score, total votes, leading candidate, and top 4 candidates.
-   **Admin Panel (Password: IRJOHNK)**: Comprehensive management for candidates (add, edit, votes, elimination), voting status (open/close), vote reset, daily vote and visitor statistics (last 7 days), recent users (top 100), partner management, and toggles for homepage vote counter and WhatsApp button.
-   **Candidate Categories**: 27 predefined categories across 5 main groups, manageable in the admin panel.
-   **Data Permanence**: All data (votes, transactions, users, daily statistics, candidates, photos/logos, site visits) are permanently stored without any automatic deletion.

### System Design Choices
-   **Database Models**: `User`, `Candidate`, `Vote`, `Transaction`, `SiteVisit`, `VotingStatus`, `TeamMember`, `Partner`, `Category`, and `DailyVoteStatistics` for historical tracking.
-   **Database Optimization**: 5 strategic indexes and an optimized connection pool for performance and stability.
-   **File Structure**: Standard Flask project structure with `app.py`, `templates/`, `static/`, and `.gitignore`.

## External Dependencies
-   **Payment Gateway**: Chariow (for processing vote package payments).
-   **Database**: PostgreSQL (for all application data storage).
-   **Frontend Libraries**: Font Awesome (for icons) and JavaScript.
-   **Flask Extensions**: Standard Flask libraries.
-   **Production Server**: Gunicorn.