# Guide d'Intégration Chariow

## Configuration Requise

### URLs de Retour Chariow

⚠️ **IMPORTANT**: Vous devez configurer ces URLs directement dans le dashboard Chariow pour chaque produit.

Pour chaque produit Chariow, configurez l'URL de retour comme suit:

**URL de Retour Unique (pour tous les produits):**
```
https://[votre-domaine-replit]/payment_confirm
```

**Note**: Après avoir configuré cette URL dans Chariow, l'utilisateur sera automatiquement redirigé vers cette page après le paiement, qu'il soit réussi ou non. Sur cette page, l'utilisateur pourra confirmer manuellement si le paiement a réussi ou échoué.

### Produits Chariow

Assurez-vous que vos produits Chariow correspondent aux URLs suivantes:

1. **STANDARD** (3000 FC = 10 votes)
   - URL: https://njpicture.mychariow.com/prd_bfhpfo/checkout
   
2. **BASIC** (5000 FC = 22 votes)
   - URL: https://njpicture.mychariow.com/prd_ud9hkt/checkout
   
3. **CLASSIC** (10000 FC = 50 votes)
   - URL: https://njpicture.mychariow.com/prd_rft2j1/checkout
   
4. **SPÉCIAL** (20000 FC = 120 votes)
   - URL: https://njpicture.mychariow.com/prd_aw8vv6/checkout
   
5. **PREMIUM** (125000 FC = 1000 votes)
   - URL: https://njpicture.mychariow.com/prd_wn4kik/checkout
   
6. **VIP** (250000 FC = 2500 votes)
   - URL: https://njpicture.mychariow.com/prd_41xu63/checkout

## Flux de Paiement

### Étapes Automatiques

1. L'utilisateur sélectionne un candidat
2. L'utilisateur choisit un bouquet
3. Une transaction est créée avec `votes_remaining=0` (en attente)
4. L'utilisateur est redirigé vers Chariow
5. Après paiement, Chariow redirige vers notre site avec le paramètre `success`
6. Si `success=true`: les votes sont activés
7. Si `success=false`: la transaction est supprimée
8. L'utilisateur peut maintenant voter avec ses votes activés

### Webhook API (Optionnel)

Si Chariow supporte les webhooks, configurez:

**Endpoint Webhook:**
```
POST https://[votre-domaine-replit]/api/chariow/webhook
```

**Format JSON Attendu:**
```json
{
  "transaction_token": "token-de-la-session",
  "status": "success",
  "signature": "signature-optionnelle"
}
```

Le webhook activera automatiquement les votes pour la transaction correspondante.

## Sécurité et Limitations

### Limitations Actuelles

⚠️ **IMPORTANT**: Sans accès à une API Chariow pour vérifier les paiements côté serveur, le système repose sur:

1. **Redirection correcte de Chariow** avec le bon paramètre `success`
2. **Honnêteté des utilisateurs** pour la page de confirmation manuelle

### Recommandations de Sécurité

Pour un système de production:

1. **Configurez Chariow** pour rediriger automatiquement avec les bons paramètres
2. **Utilisez le webhook** si Chariow le supporte
3. **Surveillez les transactions** via le panneau admin
4. **Vérifiez manuellement** les paiements suspects

### Sécurités Implémentées

✅ Transactions créées avec 0 votes par défaut
✅ Activation uniquement après confirmation explicite
✅ Nettoyage des transactions échouées
✅ Prévention du double traitement
✅ Validation des sessions utilisateur
✅ Traçabilité complète des transactions

## Tests

### Test du Flux Complet

1. Inscrivez-vous avec un nom et numéro
2. Sélectionnez un candidat
3. Choisissez un bouquet
4. Vous serez redirigé vers Chariow (simulation)
5. De retour sur le site, cliquez "Paiement Réussi"
6. Vérifiez que vos votes sont activés
7. Votez pour le candidat

### Vérification Admin

1. Connectez-vous à `/admin/login` avec le mot de passe `IRJOHNK`
2. Consultez les statistiques de votes
3. Gérez les candidats (ajouter, modifier, éliminer)
4. Ouvrez/Fermez le vote
5. Ajustez manuellement les votes si nécessaire

## Support et Maintenance

Pour toute question sur l'intégration Chariow:
1. Consultez la documentation Chariow
2. Vérifiez les logs du serveur
3. Testez avec des transactions de test Chariow
4. Contactez le support Chariow pour l'API webhook
