#!/usr/bin/env python3
"""
Script pour vider le cache de la base de données

Permet de supprimer toutes les releases en cache pour tester
les performances sans cache.
"""

from database import DatabaseManager, CachedRelease
from sqlalchemy import delete
import sys


def clear_cache():
    """Vide complètement le cache"""
    print("\n" + "=" * 70)
    print("  SUPPRESSION DU CACHE")
    print("=" * 70 + "\n")
    
    # Initialiser le gestionnaire de base de données
    db_manager = DatabaseManager()
    
    # Obtenir les statistiques avant
    stats_before = db_manager.get_cache_stats()
    print(f"Cache actuel:")
    print(f"  Total releases: {stats_before['total_cached']}")
    print(f"  Dernière semaine: {stats_before['cached_last_week']}\n")
    
    if stats_before['total_cached'] == 0:
        print("✓ Le cache est déjà vide.")
        return
    
    # Confirmation
    print(f"⚠️  ATTENTION: Vous allez supprimer {stats_before['total_cached']} releases du cache !")
    print("Les prochains exports devront re-télécharger ces données depuis l'API Discogs.")
    
    confirm = input("\nConfirmer la suppression ? (tapez 'SUPPRIMER' pour confirmer): ")
    
    if confirm != 'SUPPRIMER':
        print("\n❌ Suppression annulée.")
        return
    
    # Supprimer toutes les releases
    print("\nSuppression en cours...")
    
    try:
        session = db_manager.Session()
        
        # Supprimer toutes les entrées
        result = session.query(CachedRelease).delete()
        session.commit()
        
        print(f"✓ {result} releases supprimées")
        
        session.close()
        
        # Vérifier après
        stats_after = db_manager.get_cache_stats()
        print(f"\nCache après suppression:")
        print(f"  Total releases: {stats_after['total_cached']}")
        
        if stats_after['total_cached'] == 0:
            print("\n✓ Cache vidé avec succès !")
        else:
            print(f"\n⚠️  Il reste {stats_after['total_cached']} releases")
    
    except Exception as e:
        print(f"\n❌ ERREUR lors de la suppression: {e}")
        import traceback
        traceback.print_exc()


def clear_old_cache(days=30):
    """Supprime uniquement les entrées anciennes"""
    print("\n" + "=" * 70)
    print(f"  SUPPRESSION DU CACHE ANCIEN (>{days} jours)")
    print("=" * 70 + "\n")
    
    db_manager = DatabaseManager()
    
    print(f"Suppression des releases mises à jour il y a plus de {days} jours...\n")
    
    try:
        count = db_manager.clear_old_cache(days)
        print(f"✓ {count} releases supprimées")
        
        # Nouvelles stats
        stats = db_manager.get_cache_stats()
        print(f"\nCache restant:")
        print(f"  Total releases: {stats['total_cached']}")
        
    except Exception as e:
        print(f"❌ ERREUR: {e}")


def show_cache_info():
    """Affiche les informations détaillées du cache"""
    print("\n" + "=" * 70)
    print("  INFORMATIONS DU CACHE")
    print("=" * 70 + "\n")
    
    db_manager = DatabaseManager()
    stats = db_manager.get_cache_stats()
    
    print(f"Total releases en cache: {stats['total_cached']}")
    print(f"Releases de la dernière semaine: {stats['cached_last_week']}")
    
    if stats['total_cached'] > 0:
        # Obtenir quelques infos supplémentaires
        try:
            session = db_manager.Session()
            
            # Première et dernière release
            first = session.query(CachedRelease).order_by(CachedRelease.created_at).first()
            last = session.query(CachedRelease).order_by(CachedRelease.created_at.desc()).first()
            
            if first and last:
                print(f"\nPremière release cachée: {first.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Dernière release cachée: {last.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Quelques exemples
            print("\nExemples de releases en cache:")
            examples = session.query(CachedRelease).limit(5).all()
            for ex in examples:
                print(f"  - {ex.artists} - {ex.title} ({ex.year})")
            
            session.close()
            
        except Exception as e:
            print(f"\n⚠️  Impossible d'obtenir les détails: {e}")
    
    print()


def main():
    """Menu principal"""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == '--clear' or command == '-c':
            clear_cache()
            return
        elif command == '--info' or command == '-i':
            show_cache_info()
            return
        elif command == '--old':
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            clear_old_cache(days)
            return
        elif command == '--help' or command == '-h':
            print("\nUsage:")
            print("  python clear_cache.py             # Menu interactif")
            print("  python clear_cache.py --clear     # Vider tout le cache")
            print("  python clear_cache.py --info      # Afficher les infos")
            print("  python clear_cache.py --old [N]   # Supprimer cache >N jours")
            print()
            return
    
    # Menu interactif
    while True:
        print("\n" + "=" * 70)
        print("  GESTION DU CACHE")
        print("=" * 70 + "\n")
        
        print("Options:")
        print("  1. Afficher les informations du cache")
        print("  2. Vider complètement le cache")
        print("  3. Supprimer le cache ancien (>30 jours)")
        print("  4. Quitter")
        
        choice = input("\nVotre choix (1-4): ").strip()
        
        if choice == '1':
            show_cache_info()
        elif choice == '2':
            clear_cache()
        elif choice == '3':
            days_input = input("Nombre de jours (défaut: 30): ").strip()
            days = int(days_input) if days_input else 30
            clear_old_cache(days)
        elif choice == '4':
            print("\nAu revoir !")
            break
        else:
            print("\n❌ Choix invalide")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrompu par l'utilisateur")
    except Exception as e:
        print(f"\n\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
