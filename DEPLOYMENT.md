# Mental Health Chatbot - Deployment Guide 🚀

## 📱 **Complete Deployment & Mobile Access Strategy**

### **1. Web Deployment (Azure App Service)**

#### **Prerequisites:**
```bash
# Install Azure CLI
winget install Microsoft.AzureCLI

# Install Azure Developer CLI
winget install Microsoft.Azd

# Login to Azure
az login
azd auth login
```

#### **Quick Deployment:**
```bash
# Clone and navigate to project
cd mental-health-chatbot

# Initialize AZD project
azd init

# Deploy to Azure (creates all resources)
azd up
```

### **2. Mobile Access Options**

#### **Option A: Progressive Web App (PWA) - Recommended ✨**
- **Installable**: Users can install from browser
- **Offline Support**: Works without internet
- **Native Feel**: Behaves like a native app
- **Cross-Platform**: Works on all devices

**Features Added:**
- ✅ App manifest for installation
- ✅ Service worker for offline functionality  
- ✅ Mobile-responsive design
- ✅ App icons and shortcuts
- ✅ Push notifications ready

#### **Option B: Native Mobile App**
Use frameworks like:
- **React Native** (JavaScript)
- **Flutter** (Dart)
- **Ionic** (HTML/CSS/JS)

### **3. Deployment Options**

#### **🔥 Option 1: Azure App Service (Recommended)**
- **Cost**: ~$13/month (Basic tier)
- **Benefits**: Auto-scaling, SSL, custom domain
- **Deployment**: `azd up`

#### **🆓 Option 2: Free Hosting Alternatives**
1. **Render.com** - Free tier available
2. **Railway.app** - $5/month
3. **Fly.io** - Free tier
4. **Heroku Alternative**: PythonAnywhere

### **4. GitHub Integration & CI/CD**

#### **Setup GitHub Actions:**
```yaml
# .github/workflows/deploy.yml
name: Deploy to Azure
on:
  push:
    branches: [ main ]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Setup Python
      uses: actions/setup-python@v3
      with:
        python-version: '3.11'
    - name: Deploy with AZD
      run: |
        azd auth login --client-id ${{ secrets.AZURE_CLIENT_ID }}
        azd deploy
```

### **5. Mobile Installation Guide**

#### **For Users (PWA Installation):**

**Android Chrome:**
1. Visit your deployed website
2. Tap menu (3 dots) → "Add to Home screen"
3. Tap "Add" → App installs on home screen

**iOS Safari:**
1. Visit website in Safari
2. Tap Share button → "Add to Home Screen"
3. Tap "Add" → App appears on home screen

**Desktop:**
1. Visit website in Chrome/Edge
2. Look for install icon in address bar
3. Click "Install" → App installs as desktop app

### **6. Configuration for Production**

#### **Environment Variables Needed:**
- `GOOGLE_API_KEY`: Your Gemini API key
- `SECRET_KEY`: Flask session secret
- `DATABASE_URL`: Database connection
- `FLASK_ENV`: Set to 'production'

#### **Security Features:**
- ✅ HTTPS enforcement
- ✅ Secure session management  
- ✅ SQL injection prevention
- ✅ XSS protection
- ✅ CSRF protection

### **7. Domain & SSL**

#### **Custom Domain Setup:**
1. Purchase domain (GoDaddy, Namecheap, etc.)
2. Configure DNS in Azure
3. Add custom domain in App Service
4. Enable SSL certificate (free with Azure)

**Example**: `https://mentalhealthchatbot.com`

### **8. Monitoring & Analytics**

#### **Built-in Monitoring:**
- Azure Application Insights
- Real-time error tracking
- Performance monitoring
- User analytics
- Crash reporting

### **9. Database & Storage**

#### **Production Database Options:**
1. **SQLite** (current) - Good for small apps
2. **PostgreSQL** - Recommended for production
3. **Azure SQL Database** - Managed solution

### **10. Cost Estimation**

#### **Azure Costs (Monthly):**
- **App Service B1**: ~$13
- **Storage Account**: ~$2
- **Key Vault**: ~$3
- **Application Insights**: Free tier
- **Total**: ~$18/month

#### **Free Alternatives Total Cost**: $0-5/month

---

## **🚀 Quick Start Deployment**

### **1. Immediate Deployment (5 minutes):**
```bash
# One-command deployment
azd up --template azure-webapp-python
```

### **2. Access Your App:**
- **Web**: `https://yourapp.azurewebsites.net`
- **Mobile**: Install as PWA from browser
- **Desktop**: Install from browser

### **3. Share with Users:**
```
🌐 Website: https://your-mental-health-app.azurewebsites.net
📱 Mobile: Visit website → Add to Home Screen  
💻 Desktop: Visit website → Click Install
```

---

## **📋 Post-Deployment Checklist**

- [ ] Test all chat functionality
- [ ] Verify mobile installation works
- [ ] Check analytics dashboard
- [ ] Test offline functionality
- [ ] Verify SSL certificate
- [ ] Set up monitoring alerts
- [ ] Configure custom domain (optional)
- [ ] Set up automated backups
- [ ] Test crisis detection system
- [ ] Verify sentiment analysis works

---

## **🔄 Continuous Deployment**

Every time you push to GitHub, the app automatically updates:

1. **Push code** → GitHub
2. **GitHub Actions** → Build & Test  
3. **Azure Deploy** → Update live app
4. **Users get** → Instant updates

---

## **📞 Support & Maintenance**

#### **Monitoring:**
- View logs: `azd logs`
- Monitor performance: Azure Portal
- Check errors: Application Insights

#### **Updates:**
- Code changes: Push to GitHub
- Infrastructure changes: Update Bicep files
- Dependencies: Update requirements.txt

**Your app will be:**
✅ **Accessible worldwide** 24/7
✅ **Installable** on any device  
✅ **Auto-updating** with new features
✅ **Scalable** to millions of users
✅ **Secure** with enterprise-grade security
